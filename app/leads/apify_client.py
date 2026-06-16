"""Apify lead source — code_crafter/leads-finder (actor IoSHqwTR9YGhzccez).

Field mapping verified live against the actor's schema:
  - seniority_level / functional_level / contact_location use the actor's own
    lowercase enums (mapped below)
  - company_domain must be an ARRAY
  - email_status = ["validated"]

NOTE: on the FREE Apify plan this actor only runs via the Console UI, not the API,
so an API run returns a free-plan error (surfaced clearly below). API access needs
a paid Apify plan. Apollo is the free-via-API source.
"""
import httpx
from ..config import cfg

RUN_SYNC = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}"

SENIORITY_MAP = {
    "Founder": "founder", "Chairman": "c_suite", "President": "c_suite", "CEO": "c_suite",
    "CXO": "c_suite", "Vice President": "vp", "Director": "director", "Head": "head",
    "Manager": "manager", "Senior": "senior", "Junior": "entry", "Entry Level": "entry",
    "Executive": "c_suite",
}
FUNCTIONAL_MAP = {
    "Engineering": "engineering", "Data Engineering": "engineering", "Devops": "engineering",
    "Cloud": "engineering", "Applications": "engineering", "Analytics": "engineering",
    "Research": "engineering", "Product Management": "product_management",
    "IT": "information_technology", "Security": "information_technology",
    "Cyber Security": "information_technology", "Marketing": "marketing", "Sales": "sales",
    "HR": "human_resources", "Hiring": "human_resources", "Operations": "operations",
    "Finance": "finance", "Design": "design",
}


def _pick(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return default


def build_input(filters: dict, fetch_count: int) -> dict:
    payload = {"fetch_count": max(1, fetch_count), "file_name": "Prospects",
               "email_status": ["validated"]}
    if filters.get("target_titles"):
        payload["contact_job_title"] = filters["target_titles"][:50]
    sen = [SENIORITY_MAP[s] for s in filters.get("seniority", []) if s in SENIORITY_MAP]
    if sen:
        payload["seniority_level"] = sorted(set(sen))
    fun = [FUNCTIONAL_MAP[d] for d in filters.get("departments", []) if d in FUNCTIONAL_MAP]
    if fun:
        payload["functional_level"] = sorted(set(fun))
    if filters.get("company_domain"):
        payload["company_domain"] = [filters["company_domain"]]              # must be array
    if filters.get("location_country"):
        payload["contact_location"] = [filters["location_country"].lower()]   # lowercase enum
    if filters.get("keywords"):
        payload["company_keywords"] = filters["keywords"][:20]
    return payload


def normalise(item: dict) -> dict:
    org = item.get("organization") or item.get("company") or {}
    if isinstance(org, str):
        org = {"name": org}
    first = _pick(item, "first_name", "firstName")
    last = _pick(item, "last_name", "lastName")
    name = _pick(item, "name", "full_name", "fullName")
    if not first and name:
        parts = name.split()
        first, last = parts[0], " ".join(parts[1:])
    domain = _pick(item, "company_domain", "companyDomain", "domain") or _pick(org, "primary_domain", "domain", "website_url")
    return {
        "first_name": first, "last_name": last,
        "email": _pick(item, "email", "work_email", "business_email", "emailAddress"),
        "title": _pick(item, "title", "job_title", "jobTitle", "headline", "position"),
        "company": _pick(item, "company_name", "organization_name", "companyName") or _pick(org, "name"),
        "company_domain": (domain or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/"),
        "linkedin": _pick(item, "linkedin_url", "linkedinUrl", "linkedin"),
        "location": _pick(item, "location", "city", "country"),
        "raw": item,
    }


def search(filters: dict, fetch_count: int | None = None) -> list[dict]:
    if not cfg.APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN is not set — required to use the Apify source.")
    fetch_count = fetch_count or cfg.APIFY_FETCH
    url = RUN_SYNC.format(actor=cfg.APIFY_ACTOR_ID, token=cfg.APIFY_TOKEN)
    with httpx.Client(timeout=300) as cx:
        r = cx.post(url, json=build_input(filters, fetch_count))
        r.raise_for_status()
        items = r.json()
    if isinstance(items, dict):
        items = items.get("items", [])
    # The actor signals plan/errors as a single error item.
    if items and isinstance(items[0], dict) and items[0].get("error") and not items[0].get("first_name"):
        msg = items[0]["error"]
        if "free Apify plan" in msg:
            raise RuntimeError("This Apify actor only runs via the Console UI on the FREE plan — "
                               "API access needs a paid Apify plan. Use the Apollo source instead.")
        raise RuntimeError(f"Apify actor error: {msg}")
    return [normalise(it) for it in items if isinstance(it, dict)]
