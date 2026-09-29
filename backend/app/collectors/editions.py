"""Explicitly evidenced joint editions, not a guess from alternating years.

Keep one canonical venue/CCF level for a joint publication; an alias is neither a
second publication nor proof that the canonical inventory is complete.
"""


def joint_edition(venue, year):
    if (venue, year) != ("ECAI", 2026):
        return None
    return {
        "name": "IJCAI–ECAI 2026",
        "canonical_venue": "IJCAI",
        "year": 2026,
        "sources": [
            "https://eurai.org/ecai",
            "https://www.ijcai.org/proceedings/2026/",
        ],
        "note": "Joint edition, indexed under IJCAI without duplicate ECAI/B records. This does not establish complete IJCAI coverage.",
    }


# A small, explicit calendar keeps an absent proceedings page from being treated
# as a collector failure.  It is intentionally conservative: only years for
# which the venue has a real main edition are scheduled, while future/unreleased
# proceedings are always retried; calendar observations never permanently disable them.
_NON_APPLICABLE = {
    ("ICCV", "even"),
    ("ECCV", "odd"),
    ("COLING", 2023),
}
def publication_schedule(venue, year):
    """Return the collection status for a venue/year pair.

    ``scheduled`` means that a main-volume adapter may be run.  The other
    statuses are audit states, not errors: a biennial conference can have no
    proceedings in an off-cycle year, and a future conference can have an
    accepted/program listing before its formal proceedings exist.
    """
    if (venue, "even") in _NON_APPLICABLE and year % 2 == 0:
        return {"status": "not_applicable", "reason": f"{venue} has no main edition in an even year ({year})."}
    if (venue, "odd") in _NON_APPLICABLE and year % 2 == 1:
        return {"status": "not_applicable", "reason": f"{venue} has no main edition in an odd year ({year})."}
    if (venue, year) in _NON_APPLICABLE:
        return {"status": "not_applicable", "reason": f"No main {venue} edition is scheduled for {year}."}
    if venue == "ECAI" and year == 2026:
        return {"status": "joint_edition", "reason": "ECAI 2026 is jointly published with IJCAI 2026."}
    return {"status": "scheduled", "reason": "Main edition may be collected from an official inventory."}
