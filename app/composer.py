"""Generate ONE company-level template set (main + 2 follow-ups) with merge fields,
then render it per contact for previews and sending."""
import json
import re
from .claude_client import complete_json

SYSTEM = """You are an expert job-search outreach copywriter. Write a warm, specific,
non-salesy cold email TEMPLATE from a job applicant to people at one target company.

Hard requirements for the MAIN email:
- Open by genuinely engaging with the COMPANY'S goals / mission / recent news
  (use ONLY facts from RESEARCH — never invent).
- Express sincere interest in contributing to those goals / being part of the team.
- Weave in 2-3 concrete, relevant proofs selected from the applicant's MASTER_DATA
  (pick the experiences/projects that best match the ROLE/JD; lead with the strongest).
- ONLY at the END, mention coming across the specific role (use the role title) which
  seems a great fit, and express interest. 1-2 sentences.
- 130-190 words. Plain text. First person. Sound like a real person, not a template.
- DO NOT write a greeting line or a signature — those are added by the system.

DELIVERABILITY: no links, no attachments, no images in the body.

Merge fields you MAY use (they get filled per recipient): {{first_name}}, {{title}},
{{company}}, {{connection}}. {{connection}} is an optional short shared-background
phrase (e.g. "fellow USC alum") that may be empty — if you use it, phrase the sentence
so it still reads fine when {{connection}} is blank.

Also write 2 follow-ups (40-75 words each) to send as replies if there's no response:
polite, each adds one new small proof or angle, never guilt-trips.

Return JSON:
{ "subject": "concise specific subject (no 'Re:')",
  "main": "main body template",
  "followups": ["follow-up 1", "follow-up 2"] }"""


def compose_templates(research: dict, jd_text: str, master: dict) -> dict:
    applicant = {
        "name": master.get("personal", {}).get("name") or master.get("name"),
        "summary": (master.get("summary", {}) or {}).get("active") if isinstance(master.get("summary"), dict) else master.get("summary"),
        "skills": master.get("skills", {}),
        "experiences": master.get("experience", {}).get("active_roles", [])[:6],
        "projects": master.get("projects", [])[:6],
    }
    user = (f"ROLE / JD:\n{jd_text[:3000]}\n\n"
            f"COMPANY RESEARCH:\n{json.dumps(research, ensure_ascii=False)[:3000]}\n\n"
            f"APPLICANT MASTER_DATA (select best-fit proofs):\n{json.dumps(applicant, ensure_ascii=False, default=str)[:6000]}")
    out = complete_json(SYSTEM, user, max_tokens=2200)
    out.setdefault("subject", "Interested in joining your team")
    out.setdefault("main", "")
    out.setdefault("followups", [])
    out["followups"] = (out["followups"] + ["", ""])[:2]
    return out


# ---------- per-contact rendering ----------
_MERGE = re.compile(r"\{\{\s*([a-z_]+)\s*(?:\|\s*([^}]*?))?\s*\}\}")


def render_text(template: str, contact: dict) -> str:
    vals = {
        "first_name": contact.get("first_name") or "",
        "last_name": contact.get("last_name") or "",
        "title": contact.get("title") or "",
        "company": contact.get("company") or "",
        "connection": contact.get("alumni_note") or "",
    }

    def sub(m):
        key, fallback = m.group(1), (m.group(2) or "")
        return (vals.get(key) or fallback).strip()

    text = _MERGE.sub(sub, template or "")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def signature(master: dict) -> str:
    p = master.get("personal", {})
    name = p.get("name") or master.get("name") or ""
    line2 = "M.S. Computer Science, USC"
    email = p.get("email") or ""
    phone = p.get("phone") or ""
    bits = [name, line2]
    tail = " · ".join(x for x in [email, phone] if x)
    if tail:
        bits.append(tail)
    return "<br>".join(b for b in bits if b)


def to_html(body_text: str, contact: dict, master: dict) -> str:
    """Greeting + body + minimal (link-free) signature, as simple HTML."""
    greeting = f"Hi {contact.get('first_name') or 'there'},"
    paras = "".join(f"<p style='margin:0 0 14px'>{p.strip()}</p>"
                    for p in body_text.split("\n") if p.strip())
    return ("<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
            "line-height:1.55;color:#1a1a1a\">"
            f"<p style='margin:0 0 14px'>{greeting}</p>{paras}"
            f"<p style='margin:18px 0 0'>Best,<br>{signature(master)}</p></div>")
