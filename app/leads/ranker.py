"""Rank contacts, tag a role_type, and pick the best N (to email) per company."""

RECRUITER = ("recruit", "talent", "sourcer", "people ops", "hr ")
LEADER = ("head", "director", "vp", "vice president", "chief", "founder", "principal")
MANAGER = ("manager", "lead", "supervisor")


def role_type(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in RECRUITER):
        return "recruiter"
    if any(k in t for k in LEADER):
        return "leader"
    if any(k in t for k in MANAGER):
        return "manager"
    return "other"


def _score(title: str, targets: list[str]) -> int:
    t = (title or "").lower()
    s = 0
    for target in targets:
        words = [w for w in target.lower().split() if len(w) > 2]
        hits = sum(1 for w in words if w in t)
        if hits:
            s += 30 + hits * 10
    for kw in ("recruit", "talent", "manager", "head", "director", "lead", "hiring", "people", "engineering"):
        if kw in t:
            s += 8
    return s


def rank(contacts: list[dict], filters: dict) -> list[dict]:
    targets = filters.get("target_titles", [])
    seen, scored = set(), []
    for c in contacts:
        if not (c.get("first_name") or c.get("last_name")):
            continue
        key = (c.get("first_name", "").lower(), c.get("last_name", "").lower(), c.get("company", "").lower())
        if key in seen:
            continue
        seen.add(key)
        c["role_type"] = role_type(c.get("title", ""))
        c["relevance"] = _score(c.get("title", ""), targets) + (25 if c.get("email") else 0)
        scored.append(c)
    scored.sort(key=lambda x: x["relevance"], reverse=True)
    return scored
