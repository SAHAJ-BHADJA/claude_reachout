# JD → Outreach Platform

Paste a job description → it fetches the right people, writes a personalized
**main email + 2 threaded follow-ups**, sends them on a deliverability-safe schedule
from your Gmail, tracks opens, and auto-drafts a reply (with your resume attached)
when someone responds. Built to run **in the cloud with your laptop off**.

## Flow
1. **Pick source** (Apollo 20 / Apify 30 per company) and **paste the JD**.
2. Claude parses it → fetches leads → shows First/Last/Email/Position (+ Excel export).
   It emails the **top ~6** per company; the rest stay on the list.
3. **Generate** → researches the company → writes one **template set** (main + 2 follow-ups)
   with merge fields. Flip through each recipient to preview their personalized version,
   edit the template, or tell Claude to tweak it. Upload the resume for this company.
4. **Release** → emails drip out within your sending window (warmup ramp 10→40/day,
   ~7 min throttle, business hours). Follow-ups are **replies in-thread**, sent only if
   no reply. Opens tracked invisibly.
5. **Dashboard** → per-company live status, pause/stop per company or per person, and
   reply drafts you send in one click (resume auto-attached).

## Run locally
```powershell
cd "E:\Apollo bot"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py        # http://127.0.0.1:8000
```
Banners tell you what's missing. **Connect Gmail** via the banner link. Set
`MASTER_DATA_PATH` in `.env` to your `master_resume_data.json` (already done).
For Apify, add `APIFY_TOKEN`. Apollo works with the key in `.env`.

**Local sending test:** the engine only sends when `/cron/tick` is hit. Use the
**"Run send tick"** button on the Dashboard (it asks for your `CRON_SECRET` once).

## Deploy to the cloud (laptop-off, free tier)
1. **Database — Supabase (free, doesn't expire):** create a project → copy the Postgres
   connection string → set it as `DATABASE_URL`. (Render's own free Postgres expires in 30 days; Supabase/Neon don't.)
2. **Backend — Render:** push this repo to GitHub → Render → New → **Blueprint** (uses
   `render.yaml`). Fill the secret env vars in the dashboard. Set:
   - `TRACKING_BASE_URL` = `https://<your-app>.onrender.com`
   - `GOOGLE_REDIRECT_URI` = `https://<your-app>.onrender.com/gmail/oauth/callback`
     (add this URI in your Google Cloud OAuth client too)
   - `CRON_SECRET` = a random string
   - commit `master_resume_data.json` into the repo (or set `MASTER_DATA_PATH`)
3. **Cron pinger — cron-job.org (free):** create a job that POSTs
   `https://<your-app>.onrender.com/cron/tick?secret=<CRON_SECRET>` **every 5 minutes**.
   This sends due emails *and* keeps the free Render service awake.
4. Open the Render URL, **Connect Gmail**, and use it exactly like local.

## Deliverability (handled automatically)
- Warmup ramp (10→40/day), ~7-min randomized throttle, weekday business-hours window.
- Plain-text emails, **no links/attachments in the first email** (resume goes on reply).
- Stop-on reply / bounce / unsubscribe; OOO auto-replies resume the sequence.
- Open-tracking pixel is **on** (you chose this; slightly raises spam risk).

## Honest limits
- One inbox safely tops out ~40/day — 150–200/day needs multiple inboxes (not built; usc.edu only).
- Apify needs your `APIFY_TOKEN`; first real Apify run — verify the lead columns aren't
  blank (the actor's output field names are mapped defensively).
- Open tracking under-reports (image-blocking clients); "delivered" = sent + no bounce.
- Resume generation fallback uses Tectonic (installed); normally you **upload** the resume.

## Config (.env)
Caps `APIFY_FETCH`/`APOLLO_FETCH`/`EMAIL_TOP_N`, schedule `SEND_*`/`MIN_GAP_SECONDS`/
`DAILY_HARD_CAP`/`FOLLOWUP_GAP_DAYS`, keys, and `MASTER_DATA_PATH`. Secrets live in
`.env`/Render env (git-ignored) — rotate any keys shared in chat.
