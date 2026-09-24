"""Only public snapshot files may enter the isolated site-data branch."""
import base64
import hashlib
import json

import httpx
import pytest

from app.services.snapshot import export_snapshot


def blob_sha(content):
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


class FakeGitHub:
    def __init__(self, *, existing=False, marker=True, fail=None):
        self.requests = []
        self.blobs = {}
        self.trees = {}
        self.commit = "a" * 40 if existing else None
        self.root_tree = "b" * 40
        self.marker = marker
        self.fail = fail
        if existing:
            content = b"lithub-public-snapshot-v1\n" if marker else b"other project"
            sha = blob_sha(content)
            self.blobs[sha] = content
            self.trees[self.root_tree] = [{"path": ".lithub-snapshot", "mode": "100644", "type": "blob", "sha": sha}]

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/repos/owner/repo/")
        data = json.loads(request.content) if request.content else {}
        if self.fail and self.fail == (request.method, path):
            return httpx.Response(422, json={"message": "private-token-must-not-appear"})
        if request.method == "GET" and path == "git/ref/heads/site-data":
            return httpx.Response(200, json={"object": {"sha": self.commit}}) if self.commit else httpx.Response(404)
        if request.method == "GET" and path.startswith("git/commits/"):
            return httpx.Response(200, json={"tree": {"sha": self.root_tree}})
        if request.method == "GET" and path.startswith("git/trees/"):
            return httpx.Response(200, json={"tree": self.trees.get(path.split("/")[-1], []), "truncated": False})
        if request.method == "GET" and path.startswith("git/blobs/"):
            raw = self.blobs[path.split("/")[-1]]
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(raw).decode(), "size": len(raw)})
        if request.method == "POST" and path == "git/blobs":
            raw = base64.b64decode(data["content"])
            sha = blob_sha(raw)
            self.blobs[sha] = raw
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "git/trees":
            sha = hashlib.sha1(request.content).hexdigest()
            old = {row["path"]: row for row in self.trees.get(data.get("base_tree"), [])}
            old.update({row["path"]: row for row in data["tree"]})
            self.trees[sha] = list(old.values())
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "git/commits":
            self.root_tree = data["tree"]
            return httpx.Response(201, json={"sha": hashlib.sha1(request.content).hexdigest()})
        if request.method in ("POST", "PATCH") and path in ("git/refs", "git/refs/heads/site-data"):
            self.commit = data["sha"]
            return httpx.Response(201 if request.method == "POST" else 200, json={"object": {"sha": self.commit}})
        if request.method == "POST" and path == "dispatches":
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.mark.asyncio
async def test_first_publish_uploads_only_validated_metadata_then_dispatches(session_factory, sample_paper, tmp_path):
    from app.services.snapshot_publish import publish_snapshot

    manifest = export_snapshot(session_factory, tmp_path)
    (tmp_path / ".env").write_text("private-token-must-not-appear")
    (tmp_path / "private.db").write_bytes(b"database-secret")
    github = FakeGitHub()
    async with httpx.AsyncClient(transport=httpx.MockTransport(github)) as client:
        result = await publish_snapshot(tmp_path, repository="owner/repo", token="private-token-must-not-appear", client=client)
    assert result == {"state": "dispatched", "commit": github.commit, "revision": manifest["revision"]}
    assert github.requests[-1].url.path.endswith("/dispatches")
    assert all(request.url.host == "api.github.com" for request in github.requests)
    assert all(request.headers["Authorization"] == "Bearer private-token-must-not-appear" for request in github.requests)
    uploaded = b"\n".join(github.blobs.values())
    assert b"private-token-must-not-appear" not in uploaded
    assert b"database-secret" not in uploaded
    assert b"note" not in uploaded
    assert not any("/main" in request.url.path or b'"force":true' in request.content for request in github.requests)
    event = json.loads(github.requests[-1].content)
    assert event["client_payload"]["snapshot_commit"] == github.commit


@pytest.mark.asyncio
async def test_unchanged_publish_only_redispatches_without_another_commit(session_factory, sample_paper, tmp_path):
    from app.services.snapshot_publish import publish_snapshot

    export_snapshot(session_factory, tmp_path)
    github = FakeGitHub()
    async with httpx.AsyncClient(transport=httpx.MockTransport(github)) as client:
        first = await publish_snapshot(tmp_path, repository="owner/repo", token="token", client=client)
        commits = sum(request.method == "POST" and request.url.path.endswith("/git/commits") for request in github.requests)
        second = await publish_snapshot(tmp_path, repository="owner/repo", token="token", client=client)
    assert first == second
    assert sum(request.method == "POST" and request.url.path.endswith("/git/commits") for request in github.requests) == commits
    assert sum(request.url.path.endswith("/dispatches") for request in github.requests) == 2


@pytest.mark.asyncio
async def test_update_preserves_previous_files_and_uses_nonforced_ref_update(session_factory, sample_paper, db, tmp_path):
    from app.services.snapshot_publish import publish_snapshot

    first = export_snapshot(session_factory, tmp_path)
    github = FakeGitHub()
    async with httpx.AsyncClient(transport=httpx.MockTransport(github)) as client:
        await publish_snapshot(tmp_path, repository="owner/repo", token="token", client=client)
        sample_paper.title = "Updated metadata"
        db.commit()
        second = export_snapshot(session_factory, tmp_path)
        await publish_snapshot(tmp_path, repository="owner/repo", token="token", client=client)
    root = github.trees[github.root_tree]
    snapshot_tree = github.trees[next(row["sha"] for row in root if row["path"] == "snapshot")]
    paths = {row["path"] for row in snapshot_tree}
    assert first["chunks"][0]["path"] in paths
    assert second["chunks"][0]["path"] in paths
    update = next(request for request in reversed(github.requests) if request.method == "PATCH")
    assert json.loads(update.content)["force"] is False


@pytest.mark.asyncio
async def test_does_not_take_over_unmarked_branch(session_factory, sample_paper, tmp_path):
    from app.services.snapshot_publish import SnapshotPublishError, publish_snapshot

    export_snapshot(session_factory, tmp_path)
    github = FakeGitHub(existing=True, marker=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(github)) as client:
        with pytest.raises(SnapshotPublishError, match="marker"):
            await publish_snapshot(tmp_path, repository="owner/repo", token="token", client=client)
    assert not any(request.method in ("POST", "PATCH") for request in github.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("repository,branch,token", [("owner/repo/evil", "site-data", "token"), ("owner/repo", "main", "token"), ("owner/repo", "site-data", ""), ("owner/repo", "site-data", "a\nb")])
async def test_invalid_configuration_makes_no_network_request(session_factory, sample_paper, tmp_path, repository, branch, token):
    from app.services.snapshot_publish import SnapshotPublishError, publish_snapshot

    export_snapshot(session_factory, tmp_path)
    github = FakeGitHub()
    async with httpx.AsyncClient(transport=httpx.MockTransport(github)) as client:
        with pytest.raises(SnapshotPublishError):
            await publish_snapshot(tmp_path, repository=repository, branch=branch, token=token, client=client)
    assert github.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [("POST", "git/blobs"), ("POST", "git/refs"), ("POST", "dispatches")])
async def test_publish_failures_are_sanitized_and_never_claim_success(session_factory, sample_paper, tmp_path, failure):
    from app.services.snapshot_publish import SnapshotPublishError, publish_snapshot

    export_snapshot(session_factory, tmp_path)
    github = FakeGitHub(fail=failure)
    async with httpx.AsyncClient(transport=httpx.MockTransport(github)) as client:
        with pytest.raises(SnapshotPublishError) as error:
            await publish_snapshot(tmp_path, repository="owner/repo", token="private-token-must-not-appear", client=client)
    assert "private-token-must-not-appear" not in str(error.value)
    if failure[1] != "dispatches":
        assert not any(request.url.path.endswith("/dispatches") for request in github.requests)
