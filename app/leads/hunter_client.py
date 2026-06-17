"""Hunter.io lead source — Domain Search returns people WITH emails directly
(no credit-gated reveal). Free plan: 25 domain-searches + 50 verifications/month.

Domain Search gives {first_name, last_name, position, value(email), department,
seniority, confidence}. We map JD departments to Hunter's department enum to keep
the limited free results relevant, then rank by title afterwards.
"""
import httpx
from ..config import cfg

DOMAIN_SEARCH = "https://api.hunter.io/v2/domain-search"
VERIFY = "https://api.hunter.io/v2/email-verifier"

# our JD departments -> Hunter's allowed department enum
DEPT_MAP = {
    "Engineering": "it", "Data Engineering": "it", "Devops": "it", "Cloud": "it",
    "Applications": "it", "IT": "it", "Security": "it", "Cyber Security": "it",
    "Analytics": "it", "Research": "it", "Design": "it",
    "Product Management": "management", "Operations": "management",
    "HR": "hr", "Hiring": "hr", "Marketing": "marketing", "Sales": "sales",
    "Finance": "finance", "Legal": "legal",
}


def _departments(filters: dict) -> str:
    out = {DEPT_MAP[d] for d in filters.get("departments", []) if d in DEPT_MAP}
    out.add("management")   # hiring managers are usually tagged 'management'
    return ",".join(sorted(out))


# Best-effort US filter: Hunter has no per-person country, so we drop people whose
# title clearly marks a non-US region. Not airtight (untagged foreign staff slip through).
NON_US_MARKERS = [
    "emea", "apac", "latam", " lac", "lac ", "mena", " anz", "dach", "benelux", "nordic",
    "asia", "pacific", "europe", "european", "middle east", "africa", "latin america",
    "caribbean", "india", "u.k.", " uk ", "uk)", "united kingdom", "ireland", "germany",
    "france", "spain", "italy", "netherlands", "brazil", "mexico", "canada", "canadian",
    "australia", "singapore", "japan", "china", "hong kong", "dubai", "uae", "poland",
    "romania", "philippines", "argentina", "colombia", "south africa", "switzerland",
]


def _us_likely(e: dict) -> bool:
    text = f"{e.get('position') or ''} {e.get('position_raw') or ''}".lower()
    return not any(m in text for m in NON_US_MARKERS)


def normalise(e: dict, org: str, domain: str) -> dict:
    return {
        "first_name": e.get("first_name") or "",
        "last_name": e.get("last_name") or "",
        "email": e.get("value") or "",
        "title": e.get("position") or "",
        "company": org or "",
        "company_domain": domain,
        "linkedin": e.get("linkedin") or "",
        "location": "",
        "confidence": e.get("confidence"),
        "raw": e,
    }


def search(filters: dict, limit: int | None = None) -> list[dict]:
    if not cfg.HUNTER_API_KEY:
        raise RuntimeError("HUNTER_API_KEY is not set — required to use the Hunter source.")
    domain = filters.get("company_domain")
    if not domain:
        raise RuntimeError("Hunter needs a company domain, but none was parsed from this JD. "
                           "Add the company website/domain to the JD text and try again.")
    params = {"domain": domain, "api_key": cfg.HUNTER_API_KEY,
              "limit": limit or cfg.HUNTER_FETCH, "type": "personal"}
    dept = _departments(filters)
    if dept:
        params["department"] = dept
    with httpx.Client(timeout=60) as cx:
        r = cx.get(DOMAIN_SEARCH, params=params)
    if r.status_code != 200:
        try:
            msg = (r.json().get("errors") or [{}])[0].get("details") or r.text
        except Exception:
            msg = r.text
        if r.status_code in (429, 402) or "too many" in msg.lower() or "usage" in msg.lower():
            raise RuntimeError("Hunter monthly free quota reached (25 searches/month). "
                               "Resets next month, or switch source.")
        if r.status_code == 401:
            raise RuntimeError("Hunter API key is invalid.")
        raise RuntimeError(f"Hunter error: {msg[:200]}")
    data = r.json().get("data", {})
    org = data.get("organization") or ""
    dom = data.get("domain") or domain
    emails = [e for e in data.get("emails", []) if e.get("value")]
    us = [e for e in emails if _us_likely(e)]
    # If the US filter removes everyone (over-aggressive), fall back to all.
    chosen = us if us else emails
    return [normalise(e, org, dom) for e in chosen]
