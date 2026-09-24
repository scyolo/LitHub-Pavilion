"""Local collection/export lifecycle; public readers never need to connect to this process."""
import asyncio
import json
import logging
import time
from contextlib import suppress
from datetime import datetime, timezone

from app.config import settings
from app.services.snapshot import _atomic_write, _json_bytes, export_snapshot, validate_snapshot

log = logging.getLogger("lithub.site_sync")


async def publish_snapshot(*args, **kwargs):
    from app.services.snapshot_publish import publish_snapshot as publish

    return await publish(*args, **kwargs)


async def deployed_revision(*args, **kwargs):
    from app.services.snapshot_publish import deployed_revision as check

    return await check(*args, **kwargs)


class SiteSync:
    def __init__(self, session_factory, pipeline, *, config=None):
        self.session_factory = session_factory
        self.pipeline = pipeline
        self.config = config or settings
        self._lock = asyncio.Lock()
        self._startup_task = None
        self._retry_task = None
        self._closing = False
        self._manifest = None
        self._dispatched_revision = None
        self._dispatched_at = 0.0
        self._state = {
            "snapshot_status": "pending" if self.config.snapshot_enabled else "disabled",
            "publication_status": "pending" if self.config.pages_publish_enabled else "disabled",
            "revision": None, "generated_at": None, "paper_count": None, "commit": None,
            "last_attempt_at": None, "message": None,
        }
        self._state_path = self.config.snapshot_dir.with_name(self.config.snapshot_dir.name + "-state.json")
        self._restore_dispatch()

    def _restore_dispatch(self):
        try:
            if self._state_path.is_symlink() or self._state_path.stat().st_size > 4096:
                return
            saved = json.loads(self._state_path.read_text(encoding="utf-8"))
            if (saved.get("repository") == self.config.pages_repository
                    and saved.get("site_url", "") == self.config.pages_site_url
                    and saved.get("publication_status") in ("dispatched", "deployed")):
                self._dispatched_revision = saved.get("revision")
                self._dispatched_at = float(saved.get("dispatched_at", 0))
                self._state["publication_status"] = saved["publication_status"]
                self._state["commit"] = saved.get("commit")
        except (OSError, ValueError, AttributeError):
            pass

    def status(self):
        return {**self._state, "startup_crawl_enabled": self.config.startup_crawl_enabled}

    def start(self):
        if self._startup_task is not None:
            return
        self._startup_task = asyncio.create_task(self._startup(), name="site-startup")
        if self.config.pages_publish_enabled:
            self._retry_task = asyncio.create_task(self._retry_loop(), name="site-publication-retry")

    async def _startup(self):
        if self.config.startup_crawl_enabled:
            while not self._closing:
                if await self.pipeline.submit_startup(self.config.startup_years):
                    break
                log.warning("Startup collection will resume after the active collection finishes")
                await self.pipeline.wait_idle()
                await asyncio.sleep(1)
        if self.config.snapshot_enabled and not self._closing:
            await self.refresh()

    async def wait_startup(self):
        if self._startup_task:
            await asyncio.shield(self._startup_task)

    async def _worker(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def refresh(self):
        if not self.config.snapshot_enabled or self._closing:
            return
        async with self._lock:
            self._state["snapshot_status"] = "exporting"
            try:
                manifest = await self._worker(export_snapshot, self.session_factory, self.config.snapshot_dir)
            except ValueError as exc:
                self._state["snapshot_status"] = "waiting_for_data" if "empty snapshot" in str(exc) else "failed"
                self._state["message"] = "尚无可发布论文，采集后再导出。" if "empty snapshot" in str(exc) else "快照校验未通过；上次成功的网站数据未被替换。"
                log.warning("Snapshot export did not produce a new valid version")
                return
            except Exception:
                self._state["snapshot_status"] = "failed"
                self._state["message"] = "快照导出失败；上次成功的网站数据未被替换。"
                log.error("Snapshot export failed; existing manifest retained")
                return
            self._manifest = manifest
            self._state.update(snapshot_status="ready", revision=manifest["revision"], generated_at=manifest["generated_at"],
                               paper_count=manifest["paper_count"], message=None)
            await self._publish()

    async def _publish(self):
        if not self.config.pages_publish_enabled or not self._manifest or self._closing:
            return
        if self._manifest["revision"] == self._dispatched_revision:
            if self._state["publication_status"] != "deployed":
                self._state["publication_status"] = "dispatched"
            return
        self._state["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        try:
            token_file = self.config.pages_token_file
            if not self.config.pages_repository or token_file.stat().st_size > 4096:
                raise ValueError("Missing publication configuration")
            token = token_file.read_text(encoding="utf-8").strip()
            if not token or any(character.isspace() for character in token):
                raise ValueError("Missing publication credential")
        except (OSError, ValueError):
            self._state.update(publication_status="needs_credentials", message="本地快照已就绪；请配置目标仓库及只读挂载的 GitHub 令牌文件。")
            return
        self._state["publication_status"] = "publishing"
        try:
            result = await publish_snapshot(self.config.snapshot_dir, repository=self.config.pages_repository, token=token)
            if result.get("state") != "dispatched" or result.get("revision") != self._manifest["revision"]:
                raise ValueError("Publication result does not match exported snapshot")
        except asyncio.CancelledError:
            self._state["publication_status"] = "pending"
            raise
        except Exception:
            self._state.update(publication_status="failed", message="发布未完成；保留本地快照及线上旧版本，将自动重试。")
            log.error("Snapshot publication failed; will retry without clearing the website")
            return
        self._dispatched_revision = result["revision"]
        self._dispatched_at = time.time()
        self._state.update(publication_status="dispatched", commit=result["commit"], message="已触发 GitHub Pages 构建；尚不代表部署完成。")
        await self._save_receipt()

    async def _save_receipt(self):
        try:
            await self._worker(_atomic_write, self._state_path, _json_bytes({
                "repository": self.config.pages_repository, "site_url": self.config.pages_site_url,
                "publication_status": self._state["publication_status"], "dispatched_at": self._dispatched_at,
                "revision": self._dispatched_revision, "commit": self._state["commit"],
            }))
        except (OSError, ValueError):
            log.warning("Publication receipt could not be saved")

    async def retry_publication(self):
        if self._closing or not self.config.pages_publish_enabled:
            return
        async with self._lock:
            if not self._manifest:
                try:
                    self._manifest = await self._worker(validate_snapshot, self.config.snapshot_dir)
                except ValueError:
                    return
            if self._manifest["revision"] == self._dispatched_revision:
                try:
                    online = await deployed_revision(self.config.pages_repository, site_url=self.config.pages_site_url)
                except Exception:
                    self._state["message"] = "暂时无法检查线上版本；已保留本地快照与发布回执。"
                    return
                if online == self._dispatched_revision:
                    self._state.update(publication_status="deployed", message="已确认 GitHub Pages 正在提供当前快照。")
                    await self._save_receipt()
                    return
                self._state.update(publication_status="dispatched", message="已触发构建，尚未在网站上确认当前版本；超时将重新触发。")
                if time.time() - self._dispatched_at < self.config.pages_deploy_retry_seconds:
                    return
                self._dispatched_revision = None
            await self._publish()

    async def _retry_loop(self):
        while not self._closing:
            await asyncio.sleep(self.config.pages_retry_seconds)
            await self.retry_publication()

    async def shutdown(self):
        self._closing = True
        for task in (self._startup_task, self._retry_task):
            if task and not task.done():
                task.cancel()
        for task in (self._startup_task, self._retry_task):
            if task:
                with suppress(asyncio.CancelledError):
                    await task
