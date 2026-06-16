"""Orchestration: search → draft → review → schedule, plus controls and exports."""
from pathlib import Path
from sqlalchemy import select, func
from openpyxl import Workbook
from .db import session
from .config import cfg
from .models import Campaign, Contact, EmailMsg, Reply, utcnow
from .data import load_master
from .leads import jd_parser, ranker, apify_client, apollo_client, hunter_client
from . import research as research_mod, enrich, scheduler
from .composer import compose_templates, render_text, to_html, signature
from . import tracking

EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"


# ---------- 1. search ----------

def run_search(jd_text: str, source: str) -> dict:
    master = load_master()
    filters = jd_parser.parse_jd(jd_text)

    if source == "apify":
        raw = apify_client.search(filters, cfg.APIFY_FETCH)
    elif source == "apollo":
        raw = apollo_client.search(filters, cfg.APOLLO_FETCH)
    elif source == "hunter":
        raw = hunter_client.search(filters, cfg.HUNTER_FETCH)   # emails included directly
    else:
        raise ValueError("source must be 'apollo', 'apify', or 'hunter'")

    ranked = ranker.rank(raw, filters)

    # Apollo search masks emails — reveal the best few via enrichment (uses credits).
    # Only enrich people Apollo flags as having an email, to avoid wasting credits.
    credits_note = ""
    if source == "apollo":
        need = cfg.EMAIL_TOP_N
        for c in ranked:
            if need <= 0:
                break
            if not c.get("email") and c.get("has_email"):
                try:
                    apollo_client.enrich(c)
                except apollo_client.ApolloCreditsError:
                    credits_note = ("Apollo email-reveal credits are exhausted on this key — "
                                    "search worked but emails can't be unlocked until credits reset "
                                    "or you switch source.")
                    break
            if c.get("email"):
                need -= 1

    with session() as s:
        camp = Campaign(jd_text=jd_text, source=source,
                        company=filters.get("company_name"),
                        company_domain=filters.get("company_domain"),
                        role_title=filters.get("role_title"),
                        parsed_json=filters, status="new")
        s.add(camp)
        s.flush()

        # choose who to email: top N with a real email
        emailable = [c for c in ranked if c.get("email")]
        chosen_ids = {id(c) for c in emailable[:cfg.EMAIL_TOP_N]}

        out = []
        for c in ranked:
            note = enrich.shared_background(c, master)
            contact = Contact(
                campaign_id=camp.id, company=c.get("company"), company_domain=c.get("company_domain"),
                first_name=c.get("first_name"), last_name=c.get("last_name"), email=c.get("email"),
                title=c.get("title"), linkedin=c.get("linkedin"), location=c.get("location"),
                relevance=c.get("relevance", 0), role_type=c.get("role_type"), alumni_note=note,
                selected=id(c) in chosen_ids, raw_json=c.get("raw", {}),
            )
            s.add(contact)
            s.flush()
            out.append({"id": contact.id, "first_name": contact.first_name, "last_name": contact.last_name,
                        "email": contact.email, "title": contact.title, "company": contact.company,
                        "relevance": contact.relevance, "role_type": contact.role_type,
                        "alumni_note": note, "selected": contact.selected})
        s.commit()
        return {"campaign_id": camp.id, "filters": filters, "company": camp.company,
                "total_found": len(raw), "to_email": len(chosen_ids), "contacts": out,
                "note": credits_note}


def set_selection(campaign_id: int, contact_ids: list[int]):
    with session() as s:
        for c in s.execute(select(Contact).where(Contact.campaign_id == campaign_id)).scalars().all():
            c.selected = c.id in contact_ids
        s.commit()


# ---------- 2. drafts ----------

def generate_drafts(campaign_id: int, instruction: str = "") -> dict:
    master = load_master()
    with session() as s:
        camp = s.get(Campaign, campaign_id)
        if not camp.research_json:
            camp.research_json = research_mod.research_company(camp.company or "", camp.company_domain or "")
        jd = camp.jd_text + (f"\n\nEXTRA INSTRUCTION: {instruction}" if instruction else "")
        templates = compose_templates(camp.research_json, jd, master)
        camp.templates_json = templates
        camp.status = "drafted"
        # clear old draft emails, rebuild for selected active contacts
        for e in s.execute(select(EmailMsg).where(
                EmailMsg.campaign_id == campaign_id, EmailMsg.status == "draft")).scalars().all():
            s.delete(e)
        s.flush()
        contacts = s.execute(select(Contact).where(
            Contact.campaign_id == campaign_id, Contact.selected.is_(True),
            Contact.status == "active")).scalars().all()
        for c in contacts:
            cd = _cd(c)
            _make_email(s, camp.id, c.id, 0, templates["subject"], render_text(templates["main"], cd))
            for i, fu in enumerate(templates["followups"], start=1):
                _make_email(s, camp.id, c.id, i, f"Re: {templates['subject']}", render_text(fu, cd))
        s.commit()
        return preview(campaign_id)


def _make_email(s, cid, contact_id, seq, subject, body):
    s.add(EmailMsg(campaign_id=cid, contact_id=contact_id, seq=seq, subject=subject,
                   body_text=body, status="draft", tracking_id=tracking.new_id()))


def _cd(c: Contact) -> dict:
    return {"first_name": c.first_name, "last_name": c.last_name, "title": c.title,
            "company": c.company, "alumni_note": c.alumni_note}


def update_templates(campaign_id: int, subject, main, followups):
    """Save edited templates and re-render every draft email."""
    with session() as s:
        camp = s.get(Campaign, campaign_id)
        t = dict(camp.templates_json or {})
        if subject is not None: t["subject"] = subject
        if main is not None: t["main"] = main
        if followups is not None: t["followups"] = followups
        camp.templates_json = t
        for e in s.execute(select(EmailMsg).where(
                EmailMsg.campaign_id == campaign_id, EmailMsg.status == "draft")).scalars().all():
            c = s.get(Contact, e.contact_id)
            cd = _cd(c)
            if e.seq == 0:
                e.subject, e.body_text = t["subject"], render_text(t["main"], cd)
            else:
                e.subject = f"Re: {t['subject']}"
                e.body_text = render_text(t["followups"][e.seq - 1], cd)
        s.commit()


def preview(campaign_id: int) -> dict:
    """Templates + per-contact rendered preview for the review screen."""
    master = load_master()
    with session() as s:
        camp = s.get(Campaign, campaign_id)
        contacts = s.execute(select(Contact).where(
            Contact.campaign_id == campaign_id, Contact.selected.is_(True))).scalars().all()
        people = []
        for c in contacts:
            cd = _cd(c)
            emails = s.execute(select(EmailMsg).where(
                EmailMsg.contact_id == c.id).order_by(EmailMsg.seq)).scalars().all()
            people.append({
                "contact_id": c.id, "name": f"{c.first_name} {c.last_name}", "email": c.email,
                "title": c.title, "alumni_note": c.alumni_note,
                "rendered": [{"email_id": e.id, "seq": e.seq, "subject": e.subject,
                              "body_text": e.body_text} for e in emails],
                "html_preview": to_html((emails[0].body_text if emails else ""), cd, master),
            })
        return {"campaign_id": campaign_id, "company": camp.company,
                "templates": camp.templates_json, "research": camp.research_json, "people": people}


# ---------- 3. resume ----------

def upload_resume(campaign_id: int, filename: str, data: bytes):
    with session() as s:
        camp = s.get(Campaign, campaign_id)
        camp.resume_name = filename or "Sahaj_Bhadja_Resume.pdf"
        camp.resume_bytes = data
        s.commit()


# ---------- 4. controls ----------

def pause_campaign(cid):  _set_campaign_status(cid, "paused")
def resume_campaign(cid): _set_campaign_status(cid, "sending")


def stop_campaign(cid):
    with session() as s:
        camp = s.get(Campaign, cid)
        camp.status = "stopped"
        for e in s.execute(select(EmailMsg).where(
                EmailMsg.campaign_id == cid, EmailMsg.status.in_(["scheduled", "draft"]))).scalars().all():
            e.status = "stopped"
        s.commit()


def stop_contact(contact_id):
    with session() as s:
        c = s.get(Contact, contact_id)
        c.status = "stopped"
        for e in s.execute(select(EmailMsg).where(
                EmailMsg.contact_id == contact_id, EmailMsg.status.in_(["scheduled", "draft"]))).scalars().all():
            e.status = "stopped"
        s.commit()


def _set_campaign_status(cid, status):
    with session() as s:
        s.get(Campaign, cid).status = status
        s.commit()


# ---------- 5. exports + status ----------

def export_excel(campaign_id: int) -> str:
    with session() as s:
        rows = s.execute(select(Contact).where(
            Contact.campaign_id == campaign_id).order_by(Contact.relevance.desc())).scalars().all()
        wb = Workbook(); ws = wb.active; ws.title = "Leads"
        ws.append(["First Name", "Last Name", "Email", "Position", "Company"])
        for r in rows:
            ws.append([r.first_name, r.last_name, r.email, r.title, r.company])
        out = EXPORTS_DIR / f"leads_campaign_{campaign_id}.xlsx"
        wb.save(out)
        return str(out)


def list_campaigns() -> list[dict]:
    with session() as s:
        out = []
        for camp in s.execute(select(Campaign).order_by(Campaign.id.desc())).scalars().all():
            sent = s.execute(select(func.count(EmailMsg.id)).where(
                EmailMsg.campaign_id == camp.id, EmailMsg.status == "sent")).scalar()
            opened = s.execute(select(func.count(EmailMsg.id)).where(
                EmailMsg.campaign_id == camp.id, EmailMsg.open_count > 0)).scalar()
            replied = s.execute(select(func.count(Contact.id)).where(
                Contact.campaign_id == camp.id, Contact.status == "replied")).scalar()
            out.append({"id": camp.id, "company": camp.company, "role": camp.role_title,
                        "status": camp.status, "sent": sent, "opened": opened, "replied": replied})
        return out


def campaign_status(campaign_id: int) -> dict:
    with session() as s:
        rows = []
        q = select(EmailMsg, Contact).join(Contact, Contact.id == EmailMsg.contact_id).where(
            EmailMsg.campaign_id == campaign_id).order_by(Contact.id, EmailMsg.seq)
        for e, c in s.execute(q).all():
            rows.append({"email_id": e.id, "contact_id": c.id, "seq": e.seq,
                         "name": f"{c.first_name} {c.last_name}", "email": c.email,
                         "company": c.company, "contact_status": c.status, "status": e.status,
                         "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
                         "sent_at": e.sent_at.isoformat() if e.sent_at else None,
                         "open_count": e.open_count, "error": e.error})
        return {"rows": rows}


def list_replies() -> list[dict]:
    with session() as s:
        out = []
        for r in s.execute(select(Reply).where(Reply.status != "dismissed").order_by(Reply.id.desc())).scalars().all():
            c = s.get(Contact, r.contact_id)
            out.append({"id": r.id, "name": f"{c.first_name} {c.last_name}" if c else "",
                        "company": c.company if c else "", "intent": r.intent,
                        "snippet": r.snippet, "draft": r.draft_text, "status": r.status})
        return out


def daily_counter() -> dict:
    with session() as s:
        cap = scheduler.daily_cap(s)
        sent = scheduler._sent_today(s)
        return {"sent_today": sent, "cap": cap, "in_window": scheduler.in_window()}
