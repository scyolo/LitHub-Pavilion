"""Resolve OpenAlex source IDs for venues that lack one (1 request each)."""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy.orm import sessionmaker

from app.collectors.http_client import PublicTransport
from app.collectors.openalex import resolve_source_id
from app.config import settings
from app.db import _make_engine, db_file_path
from app.models import Venue
from app.ratelimit import AsyncTokenBucket

import httpx

ABBR = [a.strip() for a in """ICCV|ACM MM|COLING|ICME|CIKM|ECAI|NAACL|DAC|CCS|ASE
ICCAD|ICDM|ISMAR|UIST|FOCS|SC|ASIACRYPT|MICRO|ICCD|WISE|ICSME|SDM|ICNP|ACSAC
ACM SIGOPS ATC|MobiHoc|ITC|TCC|ISSRE|RTSS|ESEM|SoCC|ICSOC|RAID|ISWC|SRDS|IPSN|PACT
HOT CHIPS|Middleware|WINE|CADE|CoNEXT|HotOS|GROUP|ISS|CODES+ISSS|MSST|EMSOFT|SCA
HiPEAC|VEE|Performance|LISA|IEEE VIS|Eurographics|EuroVis|SGP|EGSR|PG|SPM|ECSCW
CSCW|NeurIPS""".replace("\n", "|").split("|") if a.strip()]


async def main():
    engine = _make_engine("sqlite:///" + db_file_path().as_posix())
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()

    transport = PublicTransport(dns_mode=settings.outbound_dns_mode)
    limiter = AsyncTokenBucket(settings.openalex_rps)
    resolved = skipped = 0
    found = {}

    async with httpx.AsyncClient(headers={"User-Agent": settings.effective_user_agent},
                                 timeout=httpx.Timeout(25, read=45),
                                 follow_redirects=True, trust_env=False,
                                 transport=transport) as client:
        for abbr in ABBR:
            venue = s.query(Venue).filter(Venue.abbr == abbr, Venue.active == 1).one_or_none()
            if venue is None:
                print(f"{abbr:22s} SKIP not active")
                continue
            if venue.openalex_source_id:
                print(f"{abbr:22s} has {venue.openalex_source_id}")
                skipped += 1
                continue
            try:
                sid = await resolve_source_id(client, limiter, venue.name, settings.contact_email)
                if sid:
                    venue.openalex_source_id = sid
                    s.commit()
                    resolved += 1
                    found[abbr] = sid
                    print(f"{abbr:22s} -> {sid}")
                else:
                    print(f"{abbr:22s} no match")
            except Exception as exc:
                print(f"{abbr:22s} ERR {type(exc).__name__}: {str(exc)[:70]}")
                if "Budget" in type(exc).__name__:
                    break
            await asyncio.sleep(0.15)

    await transport.aclose()
    s.close()
    engine.dispose()
    print(f"\nresolved={resolved} skipped={skipped}")
    print(found)


if __name__ == "__main__":
    asyncio.run(main())
