"""FastAPI app: dashboard, pipeline, scheduling, tracking, cron tick, OAuth."""
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import Response, FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select

from .db import init_db, session
from .models import EmailMsg, Event, utcnow
from .config import cfg
from .data import master_exists
from . import services, scheduler, replies, gmail_client, tracking

app = FastAPI(title="JD → Outreach")
# Allow the IDE preview pane (null/other origin) to call the API.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def _startup():
    # Non-fatal: bind the port even if the DB is briefly unreachable so Render
    # doesn't kill the service. Schema is (re)ensured lazily on the cron tick.
    import logging
    try:
        init_db()
    except Exception as e:
        logging.getLogger("uvicorn.error").error(f"init_db failed at startup: {e}")


# ---------- models ----------
class SearchReq(BaseModel):
    jd_text: str
    source: str = "apollo"

class SelectReq(BaseModel):
    campaign_id: int
    contact_ids: list[int]

class GenReq(BaseModel):
    campaign_id: int
    instruction: str = ""

class TemplatePatch(BaseModel):
    subject: str | None = None
    main: str | None = None
    followups: list[str] | None = None

class ReleaseReq(BaseModel):
    followup_gaps: list[int] | None = None


# ---------- readiness ----------
@app.get("/api/status")
def status():
    return {
        "gmail_authorized": gmail_client.is_authorized(),
        "master_data": master_exists(),
        "apollo_ready": bool(cfg.APOLLO_API_KEYS),
        "apify_ready": bool(cfg.APIFY_TOKEN),
        "hunter_ready": bool(cfg.HUNTER_API_KEY),
        "anthropic_ready": bool(cfg.ANTHROPIC_API_KEY),
        "tracking_base_url": cfg.TRACKING_BASE_URL,
        "sender": cfg.GMAIL_SENDER_EMAIL,
        "caps": {"apify": cfg.APIFY_FETCH, "apollo": cfg.APOLLO_FETCH, "email_top_n": cfg.EMAIL_TOP_N},
        "daily": services.daily_counter(),
    }


# ---------- pipeline ----------
@app.post("/api/search")
def search(req: SearchReq):
    if not req.jd_text.strip():
        raise HTTPException(400, "jd_text is required")
    try:
        return services.run_search(req.jd_text, req.source)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/select")
def select_contacts(req: SelectReq):
    services.set_selection(req.campaign_id, req.contact_ids)
    return {"ok": True}


@app.post("/api/generate")
def generate(req: GenReq):
    try:
        return services.generate_drafts(req.campaign_id, req.instruction)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/preview/{campaign_id}")
def preview(campaign_id: int):
    return services.preview(campaign_id)


@app.patch("/api/templates/{campaign_id}")
def patch_templates(campaign_id: int, body: TemplatePatch):
    services.update_templates(campaign_id, body.subject, body.main, body.followups)
    return services.preview(campaign_id)


@app.post("/api/resume/{campaign_id}")
async def upload_resume(campaign_id: int, file: UploadFile = File(...)):
    data = await file.read()
    services.upload_resume(campaign_id, file.filename, data)
    return {"ok": True, "name": file.filename, "size": len(data)}


@app.post("/api/release/{campaign_id}")
def release(campaign_id: int, body: ReleaseReq | None = None):
    gaps = body.followup_gaps if body else None
    n = scheduler.release_campaign(campaign_id, gaps)
    return {"ok": True, "queued": n}


# ---------- controls ----------
@app.post("/api/campaign/{cid}/pause")
def pause(cid: int): services.pause_campaign(cid); return {"ok": True}

@app.post("/api/campaign/{cid}/resume")
def resume(cid: int): services.resume_campaign(cid); return {"ok": True}

@app.post("/api/campaign/{cid}/stop")
def stop(cid: int): services.stop_campaign(cid); return {"ok": True}

@app.post("/api/contact/{cid}/stop")
def stop_c(cid: int): services.stop_contact(cid); return {"ok": True}


# ---------- status / export ----------
@app.get("/api/campaigns")
def campaigns(): return {"campaigns": services.list_campaigns()}

@app.get("/api/campaign/{cid}/status")
def cstatus(cid: int): return services.campaign_status(cid)

@app.get("/api/campaign/{cid}/export")
def export(cid: int):
    p = services.export_excel(cid)
    return FileResponse(p, filename=Path(p).name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/api/daily")
def daily(): return services.daily_counter()


# ---------- replies ----------
@app.get("/api/replies")
def get_replies(): return {"replies": services.list_replies()}

@app.post("/api/reply/{rid}/send")
def reply_send(rid: int): return replies.send_reply(rid)

@app.post("/api/reply/{rid}/dismiss")
def reply_dismiss(rid: int):
    from .models import Reply
    with session() as s:
        r = s.get(Reply, rid); r.status = "dismissed"; s.commit()
    return {"ok": True}


# ---------- tracking pixel ----------
@app.get("/t/o/{tracking_id}.gif")
def pixel(tracking_id: str, request: Request):
    with session() as s:
        e = s.execute(select(EmailMsg).where(EmailMsg.tracking_id == tracking_id)).scalars().first()
        if e:
            e.open_count = (e.open_count or 0) + 1
            e.opened_at = e.opened_at or utcnow()
            s.add(Event(email_id=e.id, type="open",
                        user_agent=request.headers.get("user-agent", "")[:300],
                        ip=request.client.host if request.client else ""))
            s.commit()
    return Response(content=tracking.PIXEL_GIF, media_type="image/gif",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate, private",
                             "Pragma": "no-cache", "Expires": "0"})


# ---------- cron tick (external scheduler hits this) ----------
@app.api_route("/cron/tick", methods=["GET", "POST"])
def cron_tick(secret: str = ""):
    if secret != cfg.CRON_SECRET:
        raise HTTPException(403, "bad secret")
    try:
        init_db()   # idempotent — ensures schema once DB is reachable
    except Exception:
        pass
    try:
        replies.process_new_replies()
    except Exception:
        pass
    return scheduler.tick()


# ---------- Gmail OAuth ----------
@app.get("/gmail/auth")
def gmail_auth():
    return RedirectResponse(gmail_client.auth_url())

@app.get("/gmail/oauth/callback")
def gmail_cb(request: Request):
    try:
        gmail_client.handle_callback(str(request.url))
        return HTMLResponse("<h3>Gmail connected ✅ — you can close this tab.</h3>")
    except Exception as e:
        return HTMLResponse(f"<h3>OAuth failed</h3><pre>{e}</pre>", status_code=400)


# ---------- static ----------
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
