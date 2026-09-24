"""Publish allowlisted public snapshots atomically to a dedicated GitHub data branch."""
import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.collectors.http_client import make_client
from app.services.snapshot import MAX_FILE_BYTES, _json_bytes, validate_snapshot

_MARKER = b"lithub-public-snapshot-v1\n"
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_SHA = re.compile(r"[0-9a-f]{40}")
_FILE = re.compile(r"(?:catalog|papers)-[0-9a-f]{64}\.json")


class SnapshotPublishError(RuntimeError):
    pass


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise SnapshotPublishError("GitHub returned an invalid object identifier")
    return value


def _git_blob(content):
    # GitHub's Git Database API uses SHA-1 object IDs, not as a security checksum.
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content, usedforsecurity=False).hexdigest()


def _referenced_files(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("chunks"), list):
        raise SnapshotPublishError("Existing data branch has an invalid manifest")
    if len(manifest["chunks"]) > 4096:
        raise SnapshotPublishError("Existing snapshot has too many files")
    names = set()
    for entry in [manifest.get("catalog"), *manifest["chunks"]]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not _FILE.fullmatch(entry["path"]):
            raise SnapshotPublishError("Existing snapshot references an unsafe path")
        prefix = "catalog" if entry is manifest.get("catalog") else "papers"
        if entry["path"] != f"{prefix}-{entry.get('sha256')}.json":
            raise SnapshotPublishError("Existing snapshot references an invalid digest")
        names.add(entry["path"])
    return names


def _publication_files(directory):
    try:
        manifest = validate_snapshot(directory)
        names = _referenced_files(manifest)
        files = {"manifest.json": _json_bytes(manifest)}
        for name in sorted(names):
            path = directory / name
            if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("Unsafe snapshot file")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() not in name:
                raise ValueError("Snapshot changed during publication")
            files[name] = content
        return manifest, files
    except (ValueError, OSError):
        raise SnapshotPublishError("Local public snapshot validation failed") from None


async def _in_thread(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def publish_snapshot(directory: Path, *, repository: str, token: str, branch: str = "site-data", client: httpx.AsyncClient | None = None) -> dict:
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository) or repository.endswith(("/.", "/..")):
        raise SnapshotPublishError("Invalid GitHub repository; expected owner/repo")
    if branch != "site-data":
        raise SnapshotPublishError("Only the dedicated site-data branch may be published")
    if not isinstance(token, str) or not token or len(token) > 4096 or any(ord(character) < 33 or ord(character) > 126 for character in token):
        raise SnapshotPublishError("A valid GitHub publication credential is required")
    manifest, files = await _in_thread(_publication_files, Path(directory))
    if client is None:
        async with make_client() as owned:
            return await _publish(owned, repository, token, manifest, files)
    return await _publish(client, repository, token, manifest, files)


def pages_manifest_url(repository: str, site_url: str = "") -> str:
    from app.security import public_url_host

    if not _REPOSITORY.fullmatch(repository) or repository.endswith(("/.", "/..")):
        raise SnapshotPublishError("Invalid GitHub repository; expected owner/repo")
    owner, name = repository.split("/")
    root = site_url or f"https://{owner.lower()}.github.io/" + ("" if name.lower() == f"{owner.lower()}.github.io" else name + "/")
    public_url_host(root)
    parsed = urlsplit(root)
    if parsed.query or parsed.fragment or "\\" in root or any(part in (".", "..") for part in parsed.path.split("/")):
        raise SnapshotPublishError("Pages site URL must be a canonical public HTTPS base URL")
    return root.rstrip("/") + "/snapshot/manifest.json"


async def deployed_revision(repository: str, *, site_url: str = "", client: httpx.AsyncClient | None = None) -> str | None:
    url = pages_manifest_url(repository, site_url)

    async def check(active):
        async with active.stream("GET", url, headers={"Cache-Control": "no-cache"}, follow_redirects=False,
                                 timeout=httpx.Timeout(10)) as response:
            if response.status_code != 200:
                return None
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 1024 * 1024:
                    raise SnapshotPublishError("Published manifest is too large")
            try:
                manifest = json.loads(content)
                from app.services.snapshot import manifest_revision
                revision = manifest.get("revision")
                if manifest.get("schema_version") != 1 or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
                    return None
                return revision if revision == manifest_revision(manifest) else None
            except (ValueError, TypeError, KeyError, AttributeError):
                return None

    if client is not None:
        return await check(client)
    async with make_client() as owned:
        return await check(owned)


async def _publish(client, repository, token, manifest, files):
    base = f"https://api.github.com/repos/{repository}/"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    async def request(method, path, payload=None, *, missing=False):
        try:
            response = await client.request(method, base + path, headers=headers, json=payload, follow_redirects=False)
        except (httpx.HTTPError, ValueError):
            raise SnapshotPublishError("GitHub request failed; existing website remains unchanged") from None
        if missing and response.status_code == 404:
            return None
        if response.status_code not in (200, 201, 204):
            raise SnapshotPublishError(f"GitHub publication step failed (HTTP {response.status_code}); retry without force")
        if response.status_code == 204:
            return {}
        try:
            data = response.json()
        except ValueError:
            raise SnapshotPublishError("GitHub returned an invalid JSON response") from None
        if not isinstance(data, dict):
            raise SnapshotPublishError("GitHub returned an invalid response shape")
        return data

    async def tree(sha):
        value = await request("GET", "git/trees/" + _sha(sha))
        if value.get("truncated") or not isinstance(value.get("tree"), list) or len(value["tree"]) > 20000:
            raise SnapshotPublishError("GitHub data tree is incomplete or too large")
        result = {}
        for item in value["tree"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or item["path"] in result:
                raise SnapshotPublishError("GitHub returned an invalid tree entry")
            _sha(item.get("sha"))
            result[item["path"]] = item
        return result

    async def blob(sha, max_bytes=MAX_FILE_BYTES):
        data = await request("GET", "git/blobs/" + _sha(sha))
        if data.get("encoding") != "base64" or not isinstance(data.get("content"), str) or len(data["content"]) > max_bytes * 2:
            raise SnapshotPublishError("GitHub returned an invalid snapshot blob")
        try:
            result = base64.b64decode("".join(data["content"].split()), validate=True)
        except ValueError:
            raise SnapshotPublishError("GitHub returned an invalid blob encoding") from None
        if len(result) > max_bytes or _git_blob(result) != sha:
            raise SnapshotPublishError("GitHub snapshot blob integrity check failed")
        return result

    async def upload(content):
        encoded = await _in_thread(lambda: base64.b64encode(content).decode("ascii"))
        value = await request("POST", "git/blobs", {"content": encoded, "encoding": "base64"})
        sha = _sha(value.get("sha"))
        if sha != _git_blob(content):
            raise SnapshotPublishError("Uploaded Git blob identifier did not match")
        return sha

    ref = await request("GET", "git/ref/heads/site-data", missing=True)
    parent = _sha(ref.get("object", {}).get("sha")) if ref else None
    root_sha = None
    old_files = {}
    retained = {}
    if parent:
        commit = await request("GET", "git/commits/" + parent)
        root_sha = _sha(commit.get("tree", {}).get("sha"))
        root = await tree(root_sha)
        marker = root.get(".lithub-snapshot")
        if not marker or marker.get("type") != "blob" or marker.get("mode") != "100644" or await blob(marker["sha"], 256) != _MARKER:
            raise SnapshotPublishError("Existing site-data branch is missing the expected ownership marker")
        snapshot = root.get("snapshot")
        if snapshot:
            if snapshot.get("type") != "tree":
                raise SnapshotPublishError("Existing snapshot path is not a directory")
            old_files = await tree(snapshot["sha"])
        old_manifest = old_files.get("manifest.json")
        if old_manifest:
            if old_manifest.get("type") != "blob" or old_manifest.get("mode") != "100644":
                raise SnapshotPublishError("Existing manifest is not a regular file")
            if old_manifest["sha"] == _git_blob(files["manifest.json"]):
                await request("POST", "dispatches", {"event_type": "snapshot-updated", "client_payload": {"snapshot_commit": parent, "revision": manifest["revision"]}})
                return {"state": "dispatched", "commit": parent, "revision": manifest["revision"]}
            previous_content = await blob(old_manifest["sha"], 1024 * 1024)
            try:
                previous = json.loads(previous_content)
            except (ValueError, UnicodeError):
                raise SnapshotPublishError("Existing manifest is invalid") from None
            retained["previous-manifest.json"] = {"path": "previous-manifest.json", "mode": "100644", "type": "blob", "sha": old_manifest["sha"]}
            for name in _referenced_files(previous):
                entry = old_files.get(name)
                if not entry or entry.get("type") != "blob" or entry.get("mode") != "100644":
                    raise SnapshotPublishError("Existing snapshot references a missing or unsafe file")
                retained[name] = {"path": name, "mode": "100644", "type": "blob", "sha": entry["sha"]}
    entries = retained
    for name, content in files.items():
        previous = old_files.get(name)
        sha = _git_blob(content)
        if not previous or previous.get("sha") != sha or previous.get("mode") != "100644" or previous.get("type") != "blob":
            sha = await upload(content)
        entries[name] = {"path": name, "mode": "100644", "type": "blob", "sha": sha}
    snapshot_tree = await request("POST", "git/trees", {"tree": list(entries.values())})
    marker_sha = _git_blob(_MARKER) if parent else await upload(_MARKER)
    root_payload = {"tree": [
        {"path": ".lithub-snapshot", "mode": "100644", "type": "blob", "sha": marker_sha},
        {"path": "snapshot", "mode": "040000", "type": "tree", "sha": _sha(snapshot_tree.get("sha"))},
    ]}
    if root_sha:
        root_payload["base_tree"] = root_sha
    root_tree = await request("POST", "git/trees", root_payload)
    commit = await request("POST", "git/commits", {"message": "Update public paper snapshot " + manifest["revision"][:12], "tree": _sha(root_tree.get("sha")), "parents": [parent] if parent else []})
    commit_sha = _sha(commit.get("sha"))
    if parent:
        await request("PATCH", "git/refs/heads/site-data", {"sha": commit_sha, "force": False})
    else:
        await request("POST", "git/refs", {"ref": "refs/heads/site-data", "sha": commit_sha})
    await request("POST", "dispatches", {"event_type": "snapshot-updated", "client_payload": {"snapshot_commit": commit_sha, "revision": manifest["revision"]}})
    return {"state": "dispatched", "commit": commit_sha, "revision": manifest["revision"]}
