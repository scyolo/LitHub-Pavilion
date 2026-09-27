"""Public-network request policy. URL validation and connection-time DNS pinning are separate checks."""
import ipaddress
import socket
from urllib.parse import urlsplit


class UrlRejected(ValueError):
    pass


def public_url_host(url: str, *, https_only: bool = True) -> str:
    from app.api.serializers import safe_http_url

    safe = safe_http_url(url)
    if safe is None:
        raise UrlRejected("URL must be HTTP(S) with a public host and no credentials")
    parsed = urlsplit(safe)
    if https_only and parsed.scheme != "https":
        raise UrlRejected("Only HTTPS is allowed for remote sources")
    if parsed.port not in (None, 80, 443):
        raise UrlRejected("Non-standard remote port is not allowed")
    return parsed.hostname


def _check_resolved_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlRejected("Remote host could not be resolved") from exc
    result = []
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        mapped = getattr(address, "ipv4_mapped", None)
        if (not address.is_global or address.is_multicast or address.is_reserved
                or (mapped is not None and not mapped.is_global)):
            raise UrlRejected("Remote host resolves to a non-public address")
        if str(address) not in result:
            result.append(str(address))
    if not result:
        raise UrlRejected("Remote host has no addresses")
    return result
