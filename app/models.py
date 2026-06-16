"""ORM models. JSON + LargeBinary work on both SQLite and Postgres."""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, LargeBinary,
)
from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Setting(Base):
    """Key/value store — used to persist the Gmail OAuth token in the DB so it
    survives on ephemeral cloud filesystems (Render free tier)."""
    __tablename__ = "settings"
    key = Column(String(120), primary_key=True)
    value = Column(Text)


class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True)
    jd_text = Column(Text, nullable=False)
    source = Column(String(20), nullable=False)            # 'apollo' | 'apify'
    company = Column(String(255))
    company_domain = Column(String(255))
    role_title = Column(String(255))
    parsed_json = Column(JSON)
    research_json = Column(JSON)
    templates_json = Column(JSON)                          # {subject, main, followups[]}
    status = Column(String(20), default="new")             # new|drafted|scheduled|sending|paused|done|stopped
    resume_name = Column(String(255))
    resume_bytes = Column(LargeBinary)
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime)


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    company = Column(String(255))
    company_domain = Column(String(255))
    first_name = Column(String(120))
    last_name = Column(String(120))
    email = Column(String(255))
    title = Column(String(255))
    linkedin = Column(String(512))
    location = Column(String(255))
    relevance = Column(Integer, default=0)
    role_type = Column(String(40))                         # recruiter|manager|leader|other
    alumni_note = Column(String(512))                      # shared-background hook, if any
    selected = Column(Boolean, default=False)              # chosen to be emailed
    status = Column(String(20), default="active")          # active|replied|bounced|stopped
    raw_json = Column(JSON)
    created_at = Column(DateTime, default=utcnow)


class EmailMsg(Base):
    __tablename__ = "emails"
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    seq = Column(Integer, default=0)                       # 0 main, 1..n follow-ups
    subject = Column(String(512))
    body_text = Column(Text)                               # rendered for this contact
    status = Column(String(20), default="draft")           # draft|scheduled|sent|failed|skipped|stopped
    scheduled_at = Column(DateTime)
    sent_at = Column(DateTime)
    gmail_message_id = Column(String(255))
    gmail_thread_id = Column(String(255))
    rfc_message_id = Column(String(512))                   # Message-ID header (for threading replies)
    tracking_id = Column(String(64))
    opened_at = Column(DateTime)
    open_count = Column(Integer, default=0)
    error = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey("emails.id"))
    type = Column(String(30))                              # open|sent|bounce|reply
    user_agent = Column(String(400))
    ip = Column(String(64))
    detail = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class Reply(Base):
    __tablename__ = "replies"
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    thread_id = Column(String(255))
    snippet = Column(Text)
    intent = Column(String(40))                            # interested|referral|not_now|auto_reply|ooo|other
    draft_text = Column(Text)
    status = Column(String(20), default="new")             # new|sent|dismissed
    created_at = Column(DateTime, default=utcnow)
