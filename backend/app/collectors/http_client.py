"""HTTP transport that only connects to DNS-validated public IPs, with original TLS SNI."""
import asyncio
import ipaddress
import json
import ssl
import time

import httpcore
import httpx

from app.config import settings
from app.security import UrlRejected, _check_resolved_ips, public_url_host


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, dns_mode=None):
        self.backend = httpcore.AnyIOBackend()
        self.dns_mode = dns_mode or settings.outbound_dns_mode
        self._dns_cache = {}

    async def resolve(self, host, timeout):
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            return [str(address)]
        if self.dns_mode == "system":
            return await asyncio.wait_for(asyncio.to_thread(_check_resolved_ips, host), timeout=timeout or 15)
        cached = self._dns_cache.get(host)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        addresses, ttl = await resolve_public_dns(host, timeout or 15)
        if len(self._dns_cache) >= 256:
            self._dns_cache.clear()
        self._dns_cache[host] = (time.monotonic() + ttl, addresses)
        return addresses

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        public_url_host("https://" + host if ":" not in host else "https://[" + host + "]")
        addresses = await self.resolve(host, timeout)
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
    def __init__(self, dns_mode=None):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=PublicNetworkBackend(dns_mode),
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


def _dns_answers(payload):
    if not isinstance(payload, dict) or payload.get("Status") != 0 or payload.get("TC"):
        raise UrlRejected("Public DNS response is incomplete")
    answers = payload.get("Answer", [])
    if not isinstance(answers, list) or len(answers) > 64:
        raise UrlRejected("Public DNS answer set is invalid")
    result, ttl = [], 300
    for record in answers:
        if not isinstance(record, dict):
            raise UrlRejected("Public DNS answer is invalid")
        if record.get("type") not in (1, 28):
            continue
        if not isinstance(record.get("data"), str):
            raise UrlRejected("Public DNS returned an invalid address")
        try:
            address = ipaddress.ip_address(record["data"])
        except ValueError:
            raise UrlRejected("Public DNS returned an invalid address") from None
        public_url_host("https://" + (f"[{address}]" if address.version == 6 else str(address)))
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None and (not mapped.is_global or mapped.is_reserved or mapped.is_multicast):
            raise UrlRejected("Public DNS returned a non-public address")
        if str(address) not in result:
            result.append(str(address))
        lifetime = record.get("TTL", 0)
        ttl = min(ttl, lifetime if type(lifetime) is int and lifetime >= 0 else 0)
    if not result:
        raise UrlRejected("Public DNS returned no usable address")
    return result, ttl


async def resolve_public_dns(host, timeout=15, *, client=None):
    public_url_host("https://" + host)

    async def query(active):
        # Literal public resolver address avoids recursive use of intercepted system DNS.
        async with active.stream("GET", "https://1.1.1.1/dns-query", params={"name": host, "type": "A"},
                                 headers={"accept": "application/dns-json"}, follow_redirects=False,
                                 timeout=min(timeout, 15)) as response:
            if response.status_code != 200:
                raise UrlRejected("Public DNS request failed")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 65536:
                    raise UrlRejected("Public DNS response is too large")
            try:
                payload = json.loads(data)
            except ValueError:
                raise UrlRejected("Public DNS returned invalid JSON") from None
            return _dns_answers(payload)

    if client is not None:
        return await query(client)
    async with httpx.AsyncClient(transport=PublicTransport(dns_mode="system"), follow_redirects=False, trust_env=False) as owned:
        return await query(owned)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": settings.effective_user_agent},
        timeout=httpx.Timeout(connect=15, read=60, write=30, pool=30),
        follow_redirects=False, trust_env=False, transport=PublicTransport(),
    )
