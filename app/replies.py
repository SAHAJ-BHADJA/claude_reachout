"""Reply handling: classify intent, auto-draft a response, attach the resume on reply.
OOO / auto-replies are detected and the sequence is resumed instead of stopped."""
from sqlalchemy import select
from .db import session
from .models import Reply, Contact, Campaign, EmailMsg
from .claude_client import complete_json
from .composer import signature
from .data import load_master
from . import gmail_client

SYSTEM = """You classify a reply to a job-outreach email and draft a response.
Return JSON:
{
  "intent": "interested | referral | not_now | auto_reply | ooo | other",
  "draft": "a warm, concise reply (50-110 words) from the applicant. If interested/referral,
            propose a quick call and mention the resume is attached. If not_now, be gracious.
            If auto_reply/ooo, leave draft empty. No greeting line or signature — added by system."
}"""


def process_new_replies():
    """Classify + draft for any unprocessed replies. OOO/auto-replies resume the sequence."""
    master = load_master()
    with session() as s:
        for r in s.execute(select(Reply).where(Reply.status == "new", Reply.intent.is_(None))).scalars().all():
            contact = s.get(Contact, r.contact_id)
            ctx = (f"REPLY SNIPPET:\n{r.snippet}\n\n"
                   f"CONTEXT: outreach to {contact.first_name} {contact.last_name}, "
                   f"{contact.title} at {contact.company}.")
            try:
                out = complete_json(SYSTEM, ctx, max_tokens=500)
            except Exception:
                out = {"intent": "other", "draft": ""}
            r.intent = out.get("intent", "other")
            r.draft_text = out.get("draft", "")
            if r.intent in ("ooo", "auto_reply"):
                # not a real reply — resume the sequence
                r.status = "dismissed"
                if contact.status == "replied":
                    contact.status = "active"
                    for e in s.execute(select(EmailMsg).where(
                        EmailMsg.contact_id == contact.id, EmailMsg.seq > 0,
                        EmailMsg.status == "stopped")).scalars().all():
                        e.status = "scheduled"
        s.commit()


def send_reply(reply_id: int) -> dict:
    master = load_master()
    with session() as s:
        r = s.get(Reply, reply_id)
        if not r or r.status == "sent":
            return {"ok": False, "error": "not found or already sent"}
        contact = s.get(Contact, r.contact_id)
        campaign = s.get(Campaign, r.campaign_id)
        main = s.execute(select(EmailMsg).where(
            EmailMsg.contact_id == contact.id, EmailMsg.seq == 0)).scalars().first()
        greeting = f"Hi {contact.first_name or 'there'},"
        body = "".join(f"<p style='margin:0 0 14px'>{p.strip()}</p>"
                       for p in (r.draft_text or "").split("\n") if p.strip())
        html = ("<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.55\">"
                f"<p>{greeting}</p>{body}<p style='margin:18px 0 0'>Best,<br>{signature(master)}</p></div>")
        attachment = None
        if campaign and campaign.resume_bytes:
            attachment = (campaign.resume_name or "Sahaj_Bhadja_Resume.pdf", campaign.resume_bytes, "pdf")
        try:
            gmail_client.send(
                to_email=contact.email,
                subject=f"Re: {main.subject if main else 'Following up'}",
                html=html, thread_id=r.thread_id,
                in_reply_to=main.rfc_message_id if main else None,
                attachment=attachment,
            )
            r.status = "sent"
            s.commit()
            return {"ok": True, "attached_resume": attachment is not None}
        except Exception as e:  # noqa
            return {"ok": False, "error": str(e)[:300]}
