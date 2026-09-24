"""采集管理接口（P1/P2）：手动触发、状态、日志、重打标。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import CrawlTriggerRequest
from app.api.serializers import paper_mode
from app.config import settings
from app.models import CrawlLog

router = APIRouter(prefix="/api/crawl", tags=["crawl"])


@router.post("/trigger", status_code=202)
async def trigger(body: CrawlTriggerRequest, request: Request):
    pipeline = request.app.state.pipeline
    run_id = "c-" + uuid.uuid4().hex[:12]
    if body.scope == "weekly":
        accepted = await pipeline.submit_weekly(run_id=run_id)
    elif body.scope == "pdf":
        raise HTTPException(
            status_code=400,
            detail={"code": "PDF_DOWNLOAD_DISABLED", "message": "当前版本仅保存官方和开放链接，不支持批量下载 PDF"},
        )
    else:
        years = body.years or [2023, 2024, 2025]
        accepted = await pipeline.submit_backfill(years=years, run_id=run_id)
    if not accepted:
        # 提交是原子占位（P1-6）：拒绝时返回 409，不再出现"双 202 但任务蒸发"
        raise HTTPException(status_code=409, detail={"code": "ALREADY_RUNNING", "message": "已有任务在运行"})
    return {"run_id": run_id}


@router.post("/reclassify", status_code=202)
async def reclassify(request: Request):
    pipeline = request.app.state.pipeline
    run_id = "r-" + uuid.uuid4().hex[:12]
    if not await pipeline.submit_reclassify(run_id=run_id):
        raise HTTPException(status_code=409, detail={"code": "ALREADY_RUNNING", "message": "已有任务在运行"})
    return {"run_id": run_id}


def _schedule(request: Request) -> dict | None:
    """只读取已注册任务的真实下次运行时间，不推算 cron 或重建调度器。"""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return None
    jobs = scheduler.get_jobs()

    def next_at(ids: set[str]) -> str | None:
        times = [
            job.next_run_time for job in jobs
            if job.id in ids and getattr(job, "next_run_time", None) is not None
        ]
        return min(times).isoformat() if times else None

    return {
        "timezone": str(scheduler.timezone),
        "next_crawl_at": next_at({"weekly_crawl", "weekly_crawl_peak"}),
        "next_links_at": next_at({"links_backfill"}),
    }


@router.get("/status")
def status(request: Request):
    pipeline = request.app.state.pipeline
    return {
        "running": pipeline.status.running,
        "run_id": pipeline.status.run_id,
        "current": pipeline.status.current,
        "progress": pipeline.status.progress,
        "last_error": pipeline.status.last_error,
        "schedule": _schedule(request),
        "pdf_download_enabled": settings.pdf_download_enabled,
        "mode": paper_mode(),
        "site_sync": request.app.state.site_sync.status(),
    }


@router.get("/logs")
def logs(page: int = 1, size: int = 20, db: Session = Depends(get_db)):
    if page < 1 or not 1 <= size <= 100:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAM", "message": "page>=1 且 1<=size<=100"})
    base = db.query(CrawlLog).filter(CrawlLog.venue_id.is_(None))
    total = base.count()
    rows = (
        base.order_by(CrawlLog.started_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "run_id": r.run_id,
                "task_type": r.task_type,
                "status": r.status,
                "papers_new": r.papers_new,
                "papers_updated": r.papers_updated,
                "pdf_downloaded": r.pdf_downloaded,
                "error": r.error,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
            }
            for r in rows
        ],
    }
