"""Precomputed public dashboard scopes and bounded latest-paper cards."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.publication import publication_sort_key

CARD_KEYS = {
    "id", "title", "venue", "venue_name", "venue_type", "level", "year", "abstract_preview",
    "authors_preview", "publication_date", "created_at", "venue_confirmed", "directions",
    "first_author", "authors_count", "citation_count", "pdf_status", "pdf_source", "doi",
    "official_url", "oa_url",
}


class OverviewBuilder:
    def __init__(self, catalog, generated_at):
        self.catalog = catalog
        self.time = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        self.venues = {venue["abbr"]: venue for venue in catalog["venues"]}
        self.scopes = []
        for level in (None, "A", "B"):
            for kind in (None, "conf", "journal"):
                self.scopes.append({
                    "level": level, "type": kind, "counts": Counter(), "levels": Counter(), "types": Counter(),
                    "directions": Counter(), "venues": Counter(), "years": defaultdict(Counter),
                    "annual": defaultdict(Counter), "latest": [],
                })

    def add(self, rows):
        for row in rows:
            venue = self.venues[row["venue"]]
            try:
                created = datetime.fromisoformat((row["created_at"] or "").replace("Z", "+00:00"))
                recent = self.time - timedelta(days=7) <= created <= self.time
            except (ValueError, TypeError):
                recent = False
            for scope in self.scopes:
                if scope["level"] and not row["level"] == venue["level"] == scope["level"]:
                    continue
                if scope["type"] and venue["type"] != scope["type"]:
                    continue
                scope["counts"].update({
                    "total": 1, "with_oa_link": int(bool(row["oa_url"])),
                    "with_abstract": int(bool(row["abstract"])), "confirmed_count": int(bool(row["venue_confirmed"])),
                    "recent_count": int(recent),
                })
                scope["levels"][row["level"]] += 1
                scope["types"][row["venue_type"]] += 1
                scope["directions"].update(set(row["directions"]))
                scope["venues"][row["venue"]] += 1
                scope["years"][row["venue"]][row["year"]] += 1
                scope["annual"][row["year"]][row["level"]] += 1
                scope["latest"].append({key: row[key] for key in CARD_KEYS})
                scope["latest"].sort(key=lambda paper: (publication_sort_key(paper), paper["id"]), reverse=True)
                del scope["latest"][5:]

    def result(self):
        result = []
        for scope in self.scopes:
            configured = [venue for venue in self.catalog["venues"]
                          if (not scope["level"] or venue["level"] == scope["level"])
                          and (not scope["type"] or venue["type"] == scope["type"])]
            counts = scope["counts"]
            annual = []
            for year in range(2023, self.time.year + 1):
                values = scope["annual"][year]
                annual.append({"year": year, "A": values["A"], "B": values["B"], "total": values["A"] + values["B"]})
            dashboard = {
                **{key: counts[key] for key in ("total", "with_oa_link", "with_abstract", "confirmed_count", "recent_count")},
                "by_level": {key: scope["levels"][key] for key in ("A", "B")},
                "by_type": {key: scope["types"][key] for key in ("conf", "journal")},
                "annual": annual,
                "directions": [{**direction, "paper_count": scope["directions"][direction["code"]]}
                               for direction in self.catalog["directions"]
                               if direction["enabled"] or scope["directions"][direction["code"]]],
                "configured_venues": len(configured), "venues_with_papers": len(scope["venues"]),
                "venues": [{**venue, "paper_count": scope["venues"][venue["abbr"]],
                            "years": [{"year": year, "count": count} for year, count in sorted(scope["years"][venue["abbr"]].items())]}
                           for venue in configured],
            }
            result.append({"level": scope["level"], "type": scope["type"], "dashboard": dashboard, "latest": scope["latest"]})
        return {"version": 1, "scopes": result}
