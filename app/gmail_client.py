"""Gmail OAuth (web flow) + threaded send + reply/bounce detection.
Token is stored in the DB so it survives ephemeral cloud filesystems."""
import base64
import json
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from .config import cfg
from . import settings_store

SCOPES = ["https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_KEY = "gmail_token"


def _client_config() -> dict:
    return {"web": {
        "client_id": cfg.GOOGLE_CLIENT_ID, "client_secret": cfg.GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [cfg.GOOGLE_REDIRECT_URI]}}


def _flow() -> Flow:
    return Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=cfg.GOOGLE_REDIRECT_URI)


def auth_url() -> str:
    url, _ = _flow().authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    return url


def handle_callback(full_url: str):
    flow = _flow()
    flow.fetch_token(authorization_response=full_url)
    settings_store.put(TOKEN_KEY, flow.credentials.to_json())


def _creds() -> Credentials | None:
    raw = settings_store.get(TOKEN_KEY)
    if not raw:
        return None
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        settings_store.put(TOKEN_KEY, creds.to_json())
    return creds


def is_authorized() -> bool:
    try:
        return _creds() is not None
    except Exception:
        return False


def _svc():
    creds = _creds()
    if not creds:
        raise RuntimeError("Gmail not authorized. Connect Gmail first.")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def send(to_email: str, subject: str, html: str, thread_id: str | None = None,
         in_reply_to: str | None = None, attachment: tuple | None = None) -> dict:
    """attachment = (filename, bytes, 'pdf') or None."""
    svc = _svc()
    rfc_id = f"<{uuid.uuid4().hex}@{(cfg.GMAIL_SENDER_EMAIL.split('@')[-1] or 'mail')}>"
    outer = MIMEMultipart("mixed") if attachment else MIMEMultipart("alternative")
    outer["To"] = to_email
    outer["From"] = cfg.GMAIL_SENDER_EMAIL
    outer["Subject"] = subject
    outer["Message-ID"] = rfc_id
    if in_reply_to:
        outer["In-Reply-To"] = in_reply_to
        outer["References"] = in_reply_to
    if attachment:
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(html, "html", "utf-8"))
        outer.attach(alt)
        fname, data, _ = attachment
        part = MIMEApplication(data, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=fname)
        outer.attach(part)
    else:
        outer.attach(MIMEText(html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(outer.as_bytes()).decode()
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    sent = svc.users().messages().send(userId="me", body=body).execute()
    return {"message_id": sent.get("id"), "thread_id": sent.get("threadId"), "rfc_message_id": rfc_id}


def thread_state(thread_id: str) -> dict:
    """Inspect a thread: did the recipient reply? did it bounce?"""
    state = {"replied": False, "bounced": False, "snippet": ""}
    if not thread_id:
        return state
    try:
        svc = _svc()
        thread = svc.users().threads().get(userId="me", id=thread_id).execute()
        me = (cfg.GMAIL_SENDER_EMAIL or "").lower()
        for m in thread.get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
            sender = headers.get("from", "").lower()
            subject = headers.get("subject", "").lower()
            if "mailer-daemon" in sender or "postmaster" in sender or "undeliverable" in subject \
               or ("delivery" in subject and ("fail" in subject or "status" in subject)):
                state["bounced"] = True
            elif me and me not in sender:
                state["replied"] = True
                state["snippet"] = m.get("snippet", "")[:500]
    except Exception:
        pass
    return state
