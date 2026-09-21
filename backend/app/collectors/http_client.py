"""HTTP transport that only connects to DNS-validated public IPs, with original TLS SNI."""
import asyncio
import ssl

import httpcore
import httpx

from app.config import settings
from app.security import _check_resolved_ips, public_url_host


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        public_url_host("https://" + host if ":" not in host else "https://[" + host + "]")
        addresses = await asyncio.wait_for(asyncio.to_thread(_check_resolved_ips, host), timeout=timeout or 15)
        last_error = None
        for address in addresses:
            try:
                # Numeric IP prevents a second DNS lookup. The pool retains the original host for TLS SNI.
                return await self.backend.connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError("No public endpoint available")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are not allowed for remote requests")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, response):
        self.response = response

    async def __aiter__(self):
        try:
            async for part in self.response.aiter_stream():
                yield part
        except httpcore.TimeoutException as exc:
            raise httpx.ReadTimeout("Remote response timed out") from exc
        except httpcore.NetworkError as exc:
            raise httpx.ReadError("Remote response could not be read") from exc

    async def aclose(self):
        await self.response.aclose()


class PublicTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=PublicNetworkBackend(),
            max_connections=5, max_keepalive_connections=5,
        )

    async def handle_async_request(self, request):
        public_url_host(str(request.url))
        core_request = httpcore.Request(
            method=request.method, url=str(request.url), headers=request.headers.raw,
            content=request.stream, extensions=request.extensions,
        )
        try:
            response = await self.pool.handle_async_request(core_request)
        except httpcore.TimeoutException as exc:
            raise httpx.ConnectTimeout("Remote request timed out", request=request) from exc
        except (httpcore.NetworkError, httpcore.ProtocolError) as exc:
            raise httpx.ConnectError("Remote connection failed", request=request) from exc
        return httpx.Response(response.status, headers=response.headers, stream=ResponseStream(response), extensions=response.extensions)

    async def aclose(self):
        await self.pool.aclose()


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": settings.effective_user_agent},
        timeout=httpx.Timeout(connect=15, read=60, write=30, pool=30),
        follow_redirects=False, trust_env=False, transport=PublicTransport(),
    )
