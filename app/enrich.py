"""Detect a genuine shared-background hook between the applicant and a contact.

Honest by design: only returns a note when there's an ACTUAL signal in the
contact's data (we never fabricate an alumni connection)."""
import json


def _schools(master: dict) -> list[tuple[str, list[str]]]:
    out = []
    for e in master.get("education", []):
        inst = (e.get("institution") or "")
        aliases = [inst]
        low = inst.lower()
        if "southern california" in low:
            aliases += ["USC", "University of Southern California", "Trojan"]
        if "pandit deendayal" in low:
            aliases += ["PDEU", "Pandit Deendayal", "DAIICT"]
        out.append((inst, [a.lower() for a in aliases if a]))
    return out


def _companies(master: dict) -> list[str]:
    names = []
    for r in master.get("experience", {}).get("active_roles", []):
        if r.get("company"):
            names.append(r["company"].lower())
    return names


def shared_background(contact: dict, master: dict) -> str:
    """Return a short note like 'fellow USC alum' if the contact's data supports it."""
    blob = json.dumps(contact.get("raw", {}), default=str).lower()
    for inst, aliases in _schools(master):
        if any(a in blob for a in aliases if len(a) > 3):
            short = "USC" if "southern california" in inst.lower() else inst
            return f"fellow {short} alum"
    for comp in _companies(master):
        if len(comp) > 4 and comp in blob:
            return f"both spent time at {comp.title()}"
    # shared location (city) is a soft hook
    loc = (contact.get("location") or "").lower()
    if "los angeles" in loc or "california" in loc:
        return ""  # too weak to claim as a "connection" — skip
    return ""
