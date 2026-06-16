"""Tick-based send engine. An external cron pings /cron/tick every few minutes.
Each tick sends at most ONE due email, respecting the warmup ramp, daily cap,
throttle gap, and business-hours window — so it runs in the cloud with no
always-on worker and your laptop off."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from .db import session
from .config import cfg
from .models import Campaign, Contact, EmailMsg, Event, utcnow
from . import gmail_client, tracking
from .composer import to_html
from .data import load_master


def _local_now() -> datetime:
    return datetime.now(ZoneInfo(cfg.SEND_TIMEZONE))


def in_window(now_local: datetime | None = None) -> bool:
    n = now_local or _local_now()
    return n.weekday() in cfg.SEND_DAYS and cfg.SEND_HOUR_START <= n.hour < cfg.SEND_HOUR_END


def _add_business_days(dt: datetime, days: int) -> datetime:
    d = dt
    while days > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


def daily_cap(s) -> int:
    first = s.execute(select(func.min(EmailMsg.sent_at)).where(EmailMsg.sent_at.isnot(None))).scalar()
    if not first:
        return cfg.WARMUP_RAMP[0]
    age = (utcnow() - first.replace(tzinfo=timezone.utc) if first.tzinfo is None else utcnow() - first).days
    ramp = cfg.WARMUP_RAMP
    return ramp[age] if age < len(ramp) else cfg.DAILY_HARD_CAP


def _sent_today(s) -> int:
    start_local = _local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    return s.execute(select(func.count(EmailMsg.id)).where(
        EmailMsg.status == "sent", EmailMsg.sent_at >= start_utc)).scalar() or 0


def _last_sent(s):
    return s.execute(select(func.max(EmailMsg.sent_at)).where(EmailMsg.status == "sent")).scalar()


# ---------- stop conditions ----------

def _refresh_stop_conditions(s):
    """Mark contacts replied/bounced and cancel their pending follow-ups."""
    active = s.execute(select(Contact).where(Contact.status == "active")).scalars().all()
    for c in active:
        main = s.execute(select(EmailMsg).where(
            EmailMsg.contact_id == c.id, EmailMsg.seq == 0, EmailMsg.status == "sent")).scalars().first()
        if not main or not main.gmail_thread_id:
            continue
        st = gmail_client.thread_state(main.gmail_thread_id)
        new = None
        if st["replied"]:
            new = "replied"
            _record_reply(s, c, main.gmail_thread_id, st["snippet"])
        elif st["bounced"]:
            new = "bounced"
        if new:
            c.status = new
            for e in s.execute(select(EmailMsg).where(
                EmailMsg.contact_id == c.id,
                EmailMsg.status.in_(["scheduled", "draft"]))).scalars().all():
                e.status = "stopped"
                e.error = f"contact {new}"
    s.commit()


def _record_reply(s, contact, thread_id, snippet):
    from .models import Reply
    exists = s.execute(select(Reply).where(Reply.thread_id == thread_id)).scalars().first()
    if exists:
        return
    s.add(Reply(campaign_id=contact.campaign_id, contact_id=contact.id,
                thread_id=thread_id, snippet=snippet, status="new"))


# ---------- scheduling ----------

def release_campaign(campaign_id: int, followup_gaps: list | None = None) -> int:
    """Queue the main emails for sending; follow-ups are scheduled once the main sends."""
    with session() as s:
        camp = s.get(Campaign, campaign_id)
        if not camp:
            return 0
        camp.status = "scheduled"
        camp.started_at = camp.started_at or utcnow()
        if followup_gaps:
            t = dict(camp.templates_json or {})
            t["schedule"] = {"fu_gaps": [int(x) for x in followup_gaps]}
            camp.templates_json = t   # reassign so SQLAlchemy persists the JSON change
        n = 0
        mains = s.execute(select(EmailMsg).where(
            EmailMsg.campaign_id == campaign_id, EmailMsg.seq == 0,
            EmailMsg.status == "draft")).scalars().all()
        for e in mains:
            contact = s.get(Contact, e.contact_id)
            if contact and contact.selected and contact.email and contact.status == "active":
                e.status = "scheduled"
                e.scheduled_at = utcnow()
                n += 1
        s.commit()
        return n


def _schedule_followups(s, main: EmailMsg):
    fus = s.execute(select(EmailMsg).where(
        EmailMsg.contact_id == main.contact_id, EmailMsg.seq > 0).order_by(EmailMsg.seq)).scalars().all()
    camp = s.get(Campaign, main.campaign_id)
    gaps = ((camp.templates_json or {}).get("schedule") or {}).get("fu_gaps") or cfg.FOLLOWUP_GAP_DAYS
    base = main.sent_at or utcnow()
    for fu in fus:
        gap = gaps[min(fu.seq - 1, len(gaps) - 1)]
        fu.scheduled_at = _add_business_days(base, gap)
        fu.gmail_thread_id = main.gmail_thread_id
        fu.rfc_message_id = main.rfc_message_id  # reply target
        if fu.status == "draft":
            fu.status = "scheduled"


def _next_due(s) -> EmailMsg | None:
    paused = select(Campaign.id).where(Campaign.status.in_(["paused", "stopped", "done"]))
    q = select(EmailMsg).where(
        EmailMsg.status == "scheduled",
        EmailMsg.scheduled_at <= utcnow(),
        EmailMsg.campaign_id.notin_(paused),
    ).order_by(EmailMsg.scheduled_at, EmailMsg.seq)
    for e in s.execute(q).scalars().all():
        c = s.get(Contact, e.contact_id)
        if c and c.status == "active" and c.email:
            return e
    return None


def _send_one(s, email: EmailMsg) -> dict:
    contact = s.get(Contact, email.contact_id)
    campaign = s.get(Campaign, email.campaign_id)
    master = load_master()
    tid = email.tracking_id or tracking.new_id()
    html = tracking.inject_pixel(to_html(email.body_text, _contact_dict(contact), master), tid)

    attachment = None  # resume only goes out on REPLY (handled in replies.py), never in the sequence
    try:
        res = gmail_client.send(
            to_email=contact.email, subject=email.subject, html=html,
            thread_id=email.gmail_thread_id,
            in_reply_to=email.rfc_message_id if email.seq > 0 else None,
            attachment=attachment,
        )
        email.status = "sent"
        email.sent_at = utcnow()
        email.gmail_message_id = res["message_id"]
        email.gmail_thread_id = res["thread_id"]
        email.tracking_id = tid
        if email.seq == 0:
            email.rfc_message_id = res["rfc_message_id"]
            _schedule_followups(s, email)
        if campaign and campaign.status in ("scheduled",):
            campaign.status = "sending"
        s.add(Event(email_id=email.id, type="sent"))
        s.commit()
        return {"sent": True, "email_id": email.id}
    except Exception as e:  # noqa
        email.status = "failed"
        email.error = str(e)[:500]
        s.commit()
        return {"sent": False, "error": str(e)[:200]}


def _contact_dict(c: Contact) -> dict:
    return {"first_name": c.first_name, "last_name": c.last_name, "title": c.title,
            "company": c.company, "alumni_note": c.alumni_note}


def tick() -> dict:
    """Process one step of the queue. Called by /cron/tick."""
    with session() as s:
        if not in_window():
            return {"action": "outside_window", "local": _local_now().isoformat()}
        # refresh replies/bounces opportunistically (cheap-ish; runs each tick)
        try:
            _refresh_stop_conditions(s)
        except Exception:
            pass
        cap = daily_cap(s)
        sent_today = _sent_today(s)
        if sent_today >= cap:
            return {"action": "daily_cap_reached", "sent_today": sent_today, "cap": cap}
        last = _last_sent(s)
        if last:
            last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
            if (utcnow() - last).total_seconds() < cfg.MIN_GAP_SECONDS:
                return {"action": "throttled", "wait_s": int(cfg.MIN_GAP_SECONDS - (utcnow() - last).total_seconds())}
        due = _next_due(s)
        if not due:
            _mark_done_campaigns(s)
            return {"action": "nothing_due", "sent_today": sent_today, "cap": cap}
        result = _send_one(s, due)
        return {"action": "sent" if result.get("sent") else "send_failed",
                "sent_today": sent_today + (1 if result.get("sent") else 0), "cap": cap, **result}


def _mark_done_campaigns(s):
    for camp in s.execute(select(Campaign).where(Campaign.status == "sending")).scalars().all():
        pending = s.execute(select(func.count(EmailMsg.id)).where(
            EmailMsg.campaign_id == camp.id, EmailMsg.status.in_(["scheduled", "draft"]))).scalar()
        if not pending:
            camp.status = "done"
    s.commit()
