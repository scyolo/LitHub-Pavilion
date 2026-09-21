"""Outbound URL and connection security tests; no live network access."""
import socket
from unittest.mock import AsyncMock

import pytest

from app.security import PdfUrlRejected, UrlRejected, _check_resolved_ips, public_url_host


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "javascript:alert(1)", "http://example.org",
    "https://user:pass@example.org", "https://localhost/path", "https://127.1/",
    "https://10.1.2.3/", "https://169.254.169.254/", "https://[::1]/",
    "https://example.org:8443/path", "https://example.org\\@localhost/",
])
def test_outbound_url_rejects_non_public_targets(url):
    with pytest.raises(UrlRejected):
        public_url_host(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "100.64.0.1", "169.254.169.254", "::1", "fc00::1", "224.0.0.1"])
def test_actual_dns_resolution_rejects_every_private_address(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    with pytest.raises(PdfUrlRejected):
        _check_resolved_ips("example.org")


@pytest.mark.asyncio
async def test_network_connect_pins_the_validated_ip(monkeypatch):
    import app.collectors.http_client as module

    monkeypatch.setattr(module, "_check_resolved_ips", lambda host: ["93.184.216.34"])
    backend = module.PublicNetworkBackend()
    backend.backend = AsyncMock()
    await backend.connect_tcp("example.org", 443)
    assert backend.backend.connect_tcp.await_args.args[0] == "93.184.216.34"


@pytest.mark.asyncio
async def test_transport_does_not_dispatch_bad_hosts(monkeypatch):
    import httpx
    from app.collectors.http_client import PublicTransport

    transport = PublicTransport()
    transport.pool = AsyncMock()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UrlRejected):
            await client.get("https://localhost/secret")
    transport.pool.handle_async_request.assert_not_called()
