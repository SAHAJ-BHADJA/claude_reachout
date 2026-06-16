"""Apollo.io people search + enrichment (current API, 2026).

Apollo's search endpoint (mixed_people/api_search) returns MASKED records
(obfuscated last name, has_email flag, no email). You reveal the real name +
email by calling people/match with the person's id (uses an Apollo credit).
So: search (free-ish) → enrich the chosen few (credits) to unlock emails.
"""
import httpx
from ..config import cfg

SEARCH_URL = "{base}/mixed_people/api_search"
MATCH_URL = "{base}/people/match"


class ApolloCreditsError(Exception):
    """Raised when the Apollo plan is out of email-reveal credits."""


def _headers() -> dict:
    if not cfg.APOLLO_API_KEYS:
        raise RuntimeError("APOLLO_API_KEYS is not set — required to use the Apollo source.")
    return {"Content-Type": "application/json", "Cache-Control": "no-cache",
            "x-api-key": cfg.APOLLO_API_KEYS[0]}


def _locked(email) -> bool:
    return (not email) or "email_not_unlocked" in str(email) or "domain.com" in str(email)


def _domain(org: dict) -> str:
    d = org.get("primary_domain") or org.get("website_url") or ""
    return d.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")


def _loc(p: dict) -> str:
    return ", ".join(x for x in [p.get("city"), p.get("state"), p.get("country")] if x)


def normalise(p: dict) -> dict:
    org = p.get("organization") or {}
    email = p.get("email")
    return {
        "first_name": p.get("first_name", ""),
        "last_name": p.get("last_name") or p.get("last_name_obfuscated") or "",
        "email": "" if _locked(email) else email,
        "title": p.get("title", ""),
        "company": org.get("name", "") or p.get("organization_name", ""),
        "company_domain": _domain(org),
        "linkedin": p.get("linkedin_url", ""),
        "location": _loc(p),
        "has_email": bool(p.get("has_email")),
        "apollo_id": p.get("id"),
        "raw": p,
    }


def search(filters: dict, per_page: int | None = None) -> list[dict]:
    per_page = per_page or cfg.APOLLO_FETCH
    body = {"page": 1, "per_page": per_page}
    if filters.get("target_titles"):
        body["person_titles"] = filters["target_titles"]
    if filters.get("seniority"):
        body["person_seniorities"] = [s.lower() for s in filters["seniority"]]
    if filters.get("company_domain"):
        body["q_organization_domains_list"] = [filters["company_domain"]]
    if filters.get("location_country"):
        body["person_locations"] = [filters["location_country"]]
    with httpx.Client(timeout=120) as cx:
        r = cx.post(SEARCH_URL.format(base=cfg.APOLLO_BASE_URL), headers=_headers(), json=body)
        r.raise_for_status()
        data = r.json()
    return [normalise(p) for p in (data.get("people", []) + data.get("contacts", []))]


def enrich(contact: dict) -> dict:
    """Reveal real name + email via people/match (uses an Apollo credit)."""
    pid = contact.get("apollo_id") or (contact.get("raw") or {}).get("id")
    body = {"reveal_personal_emails": False}
    if pid:
        body["id"] = pid
    else:
        body.update({k: v for k, v in {
            "first_name": contact.get("first_name"), "last_name": contact.get("last_name"),
            "organization_name": contact.get("company"),
            "domain": contact.get("company_domain") or None,
            "linkedin_url": contact.get("linkedin") or None}.items() if v})
    try:
        with httpx.Client(timeout=120) as cx:
            r = cx.post(MATCH_URL.format(base=cfg.APOLLO_BASE_URL), headers=_headers(), json=body)
            if r.status_code == 422 and "insufficient credits" in r.text.lower():
                raise ApolloCreditsError("Apollo email-reveal credits exhausted.")
            r.raise_for_status()
            person = r.json().get("person") or {}
        if person.get("email") and not _locked(person["email"]):
            contact["email"] = person["email"]
        if person.get("last_name"):
            contact["last_name"] = person["last_name"]
        if person.get("linkedin_url"):
            contact["linkedin"] = person["linkedin_url"]
        loc = _loc(person)
        if loc:
            contact["location"] = loc
    except ApolloCreditsError:
        raise
    except Exception:
        pass
    return contact
