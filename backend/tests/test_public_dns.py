"""Encrypted public DNS supports Fake-IP networks without weakening outbound validation."""
from unittest.mock import AsyncMock

import httpx
import pytest

from app.collectors.http_client import PublicNetworkBackend, _dns_answers, resolve_public_dns
from app.security import UrlRejected


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "198.18.0.45", "100.64.0.1", "192.0.2.1", "224.0.0.1", "::1", "fc00::1", "::ffff:10.0.0.1"])
def test_encrypted_dns_rejects_every_unsafe_answer_even_with_public_peers(address):
    with pytest.raises(UrlRejected):
        _dns_answers({"Status": 0, "Answer": [{"type": 1, "data": "93.184.216.34", "TTL": 60}, {"type": 28 if ":" in address else 1, "data": address, "TTL": 60}]})


@pytest.mark.parametrize("payload", [{"Status": 2}, {"Status": 0, "TC": True}, {"Status": 0, "Answer": []}, {"Status": 0, "Answer": [{"type": 1, "data": "not-an-ip"}]}, {"Status": 0, "Answer": "invalid"}])
def test_encrypted_dns_rejects_incomplete_answers(payload):
    with pytest.raises(UrlRejected):
        _dns_answers(payload)


@pytest.mark.asyncio
async def test_encrypted_dns_uses_fixed_public_resolver_without_auth_or_redirects():
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 1, "data": "93.184.216.34", "TTL": 30}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        assert await resolve_public_dns("api.github.com", client=client) == (["93.184.216.34"], 30)
    assert requests[0].url.host == "1.1.1.1"
    assert requests[0].url.params["name"] == "api.github.com"
    assert "authorization" not in requests[0].headers


@pytest.mark.asyncio
async def test_encrypted_dns_never_follows_redirect():
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(UrlRejected):
            await resolve_public_dns("api.github.com", client=client)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_encrypted_dns_pins_answers_and_reuses_only_unexpired_results(monkeypatch):
    import app.collectors.http_client as module

    resolver = AsyncMock(return_value=(["93.184.216.34"], 60))
    monkeypatch.setattr(module, "resolve_public_dns", resolver)
    backend = PublicNetworkBackend(dns_mode="https")
    backend.backend = AsyncMock()
    await backend.connect_tcp("api.github.com", 443)
    await backend.connect_tcp("api.github.com", 443)
    resolver.assert_awaited_once()
    assert all(call.args[0] == "93.184.216.34" for call in backend.backend.connect_tcp.await_args_list)
    await backend.connect_tcp("1.1.1.1", 443)
    resolver.assert_awaited_once()
