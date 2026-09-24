"""Public deployment receipts and off-thread snapshot publication preparation."""
import asyncio
import threading

import httpx
import pytest

from app.services.snapshot import export_snapshot
from app.services.snapshot_publish import SnapshotPublishError, deployed_revision, pages_manifest_url


def test_pages_url_supports_repository_root_and_custom_domain():
    assert pages_manifest_url("Owner/repo") == "https://owner.github.io/repo/snapshot/manifest.json"
    assert pages_manifest_url("Owner/Owner.github.io") == "https://owner.github.io/snapshot/manifest.json"
    assert pages_manifest_url("owner/repo", "https://papers.example.org/reader/") == "https://papers.example.org/reader/snapshot/manifest.json"


@pytest.mark.parametrize("url", ["http://papers.example.org", "https://127.0.0.1/", "https://10.0.0.1/", "https://localhost/", "file:///tmp", "https://papers.example.org/?token=secret", "https://papers.example.org/#home", "https://papers.example.org/../private"])
@pytest.mark.asyncio
async def test_deployment_url_rejects_unsafe_targets_before_network(url):
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: seen.append(request))) as client:
        with pytest.raises((ValueError, SnapshotPublishError)):
            await deployed_revision("owner/repo", site_url=url, client=client)
    assert not seen


@pytest.mark.asyncio
async def test_deployment_check_has_no_token_and_requires_valid_revision(session_factory, sample_paper, tmp_path):
    manifest = export_snapshot(session_factory, tmp_path)
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json=manifest)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        assert await deployed_revision("owner/repo", client=client) == manifest["revision"]
        manifest["revision"] = "0" * 64
        assert await deployed_revision("owner/repo", client=client) is None
    assert all("authorization" not in request.headers for request in requests)
    assert all(request.url.host == "owner.github.io" for request in requests)
    assert requests[0].headers["cache-control"] == "no-cache"


@pytest.mark.asyncio
async def test_deployment_redirects_are_not_followed():
    seen = []

    def reply(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        assert await deployed_revision("owner/repo", client=client) is None
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_large_snapshot_preparation_does_not_block_event_loop(monkeypatch, tmp_path):
    import app.services.snapshot_publish as module

    loop_thread = threading.get_ident()
    preparation_threads = []
    finished = asyncio.Event()

    def prepare(directory):
        preparation_threads.append(threading.get_ident())
        return {"revision": "a" * 64}, {}

    async def publish(*args):
        finished.set()
        return {"state": "dispatched"}

    monkeypatch.setattr(module, "_publication_files", prepare)
    monkeypatch.setattr(module, "_publish", publish)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        await module.publish_snapshot(tmp_path, repository="owner/repo", token="test-token", client=client)
    assert finished.is_set()
    assert preparation_threads and all(value != loop_thread for value in preparation_threads)
