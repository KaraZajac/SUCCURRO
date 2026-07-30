"""Permission gate for sources under an outreach clock.

DATA-RIGHTS records a fallback policy: a source with no restrictive terms that
does not answer a permission request by its deadline may be ingested facts-only,
attributed, takedown honored. A source whose terms *do* require consent may
never be ingested on silence alone.

This module makes that policy executable rather than remembered. A gated module
calls `require(key)` before writing anything; it aborts until either the
deadline has passed or an explicit grant is recorded here.

To record a grant (a real reply from the source), set `granted` to the date of
the reply and note who said what in `grant_note`.
"""
import datetime
import sys

CLOCKS = {
    "alanon": {
        "publisher": "Al-Anon Family Group Headquarters (WSO)",
        "asked": "2026-07-19",
        "deadline": "2026-08-09",
        "consent_required": False,   # no terms of use published (verified 2026-07-20)
        "granted": None,
        "grant_note": None,
    },
    "ian": {
        "publisher": "Immigration Advocates Network (Pro Bono Net)",
        "asked": "2026-07-19",
        "deadline": "2026-08-09",
        "consent_required": False,   # no reuse restrictions found (verified 2026-07-20)
        "granted": None,
        "grant_note": None,
    },
    # Consent-required sources are listed so the gate can refuse them loudly
    # even if someone writes a module by mistake.
    "ampleharvest": {
        "publisher": "AmpleHarvest.org",
        "asked": "2026-07-19",
        "deadline": None,
        "consent_required": True,    # ToS §3: prior written consent to redistribute
        "granted": None,
        "grant_note": None,
    },
    "vivery": {
        "publisher": "Vivery / AccessFood",
        "asked": "2026-07-27",
        "deadline": None,
        "consent_required": True,
        "granted": None,
        "grant_note": None,
    },
    "griefshare": {
        "publisher": "Church Initiative (GriefShare)",
        "asked": "2026-07-27",
        "deadline": None,
        "consent_required": True,
        "granted": None,
        "grant_note": None,
    },
}


def status(key):
    c = CLOCKS[key]
    if c["granted"]:
        return True, f"granted {c['granted']}" + (f" — {c['grant_note']}" if c["grant_note"] else "")
    if c["consent_required"]:
        return False, (f"{c['publisher']} requires prior written consent; asked "
                       f"{c['asked']}, no grant recorded. Silence is not consent.")
    today = datetime.date.today().isoformat()
    if c["deadline"] and today >= c["deadline"]:
        return True, (f"no reply by {c['deadline']} (asked {c['asked']}); "
                      f"fallback policy allows facts-only ingestion")
    return False, (f"{c['publisher']} asked {c['asked']}, fallback date "
                   f"{c['deadline']} not reached (today {today})")


def require(key):
    """Abort unless this source may be ingested today."""
    ok, why = status(key)
    print(f"permission gate [{key}]: {'OPEN' if ok else 'CLOSED'} — {why}")
    if not ok:
        sys.exit(f"refusing to ingest {key}: {why}")
    return why


if __name__ == "__main__":
    for key in CLOCKS:
        ok, why = status(key)
        print(f"{'OPEN  ' if ok else 'CLOSED'} {key:14} {why}")
