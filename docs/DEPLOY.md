# Deploying Readback

API on Render (FastAPI + uvicorn, one worker), web on Vercel (Vite static
build), Postgres on Render (Neon alternative in the appendix).

Written to be followed by a person with a browser and a card, in order. Every
step where a human has to copy a value that **does not exist yet** is marked
`>> HUMAN:`. Nothing here is automated for you. Budget about 40 minutes the
first time; most of it is waiting for builds.

---

## What this deployment is, and what it is not

Readback opens the **AssemblyAI Streaming API outbound** from our server.
`server/stream/live.py` connects to `wss://streaming.assemblyai.com/v3/ws`
with the key in an `Authorization` header, sends PCM16 audio, and reads Turn
frames back. That is the only path to AssemblyAI. **Nothing at AssemblyAI ever
calls us**, so:

- there is no public callback URL to configure (the Closeout blueprint's
  `CLOSEOUT_PUBLIC_BASE_URL` has no equivalent here — do not reintroduce one);
- there is no server-side tool endpoint to expose;
- the API key never reaches the browser, and no browser token is minted.

The traffic is:

```
browser on Vercel  ──HTTPS + WSS──►  readback-api on Render  ──WSS──►  streaming.assemblyai.com
   (static page)                       (holds the key)                  (outbound only)
```

The browser talks to our server only: `POST /api/session/start`, then two
WebSockets on the same origin — `/api/session/{id}/live` (events out) and
`/api/session/{id}/audio` (PCM16 in). `web/src/lib/useLiveSession.ts` derives
the `wss://` URL from the API origin by swapping the scheme (`http`→`ws`), so
there is one origin to configure on the browser side and it must be the Render
one (step 5 explains why "same-origin" cannot work in production).

Two invariants the platform must not break:

- **Consent (ARCH 3.12).** `/api/session/start` refuses with `403` unless the
  body carries `consent.accepted: true`. `server/config.py` refuses to
  construct with `READBACK_CONSENT_REQUIRED=false` unless replay mode is on.
  `render.yaml` deliberately does not list the variable.
- **No audio at rest (ARCH 3.9).** Raw audio is never stored; `models.py`
  refuses columns that could hold it. Render's ephemeral disk is not a loophole
  for this — nothing writes audio anywhere.

---

## Step 0 — repository hygiene (do this first)

### 0a. `requirements.txt` and `requirements.lock` — both exist now

**This step is done.** Both files are in the repository, and the note below is
kept because it records why they are shaped the way they are.

What changed on 2026-09-11: `render.yaml` no longer builds with
`pip install -r requirements.txt`. It builds with

```
pip install --upgrade pip==24.3.1 && pip install --require-hashes -r requirements.lock
```

`requirements.txt` is the human list — nine direct dependencies, each with the
reason it is there. `requirements.lock` is compiled from it and carries all
twenty-nine packages, transitive ones included, pinned with their artefact
hashes; `--require-hashes` makes pip refuse anything else. Before that, about
twenty transitive packages resolved to whatever was newest at each deploy with
no verification at all, which is how a compromised or yanked release reaches
production without anyone looking.

Regenerate after any dependency change (the command is also in the lock's
header):

```
uv pip compile requirements.txt --universal --generate-hashes --python-version 3.12 --output-file requirements.lock
```

`--universal` matters: `uvicorn[standard]` needs `uvloop` only off Windows and
`colorama` only on it, so a lock compiled on a Windows machine would omit
`uvloop` and the Linux build would fail on a package pip is forbidden to fetch.

The original note, for the record:

`>> HUMAN:` create `requirements.txt` at the repository root. These are the
runtime imports of `server/` (SQLAlchemy, FastAPI, pydantic, pydantic-settings,
httpx, `websockets` for the streaming socket, `psycopg` for Postgres), pinned to
the versions the code was developed against on 2026-09-03:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.4
pydantic-settings==2.7.0
sqlalchemy==2.0.36
httpx==0.28.1
websockets==17.0.1
psycopg[binary]==3.2.3
```

`psycopg[binary]` is the one package not installed on the development machine
(it runs SQLite). It is required in production: `server/db.py` rewrites every
Postgres URL to the `postgresql+psycopg://` driver, which is psycopg 3, and
nothing else will satisfy that import. `uvicorn[standard]` brings the
server-side WebSocket implementation that the two browser sockets need.

Test-only packages (`pytest`, `pytest-asyncio`) do not belong in this file.

### 0b. Confirm no secrets are staged

`.gitignore` covers `.env` and the SQLite files, but check rather than trust:

```bash
cd /d/My_apps/Readback
git ls-files | grep -E '(^|/)\.env$|\.db(-wal|-shm)?$' && echo "STOP -- secrets staged" || echo "clean"
```

`.env` at the root currently holds a real `READBACK_ASSEMBLYAI_API_KEY`. It
must stay out of git; `.env.example` is the committed template.

### 0c. Push to GitHub

Render and Vercel both deploy from a git host. The repository already has
commits; push it (the owner does this — no agent commits):

```bash
gh repo create readback --private --source=. --push
```

---

## Step 1 — the AssemblyAI key (manual, browser)

`>> HUMAN:` sign up at <https://www.assemblyai.com/>, open the dashboard, copy
the API key. Keep it in a password manager. It goes into the Render dashboard
in step 3 and nowhere else — not into a file in this repository, not into
Vercel.

Check the key does the one thing this deployment needs — open a streaming
socket. This is not a `curl` (streaming is WebSocket-only, and the key goes in
a raw `Authorization` header with **no** `Bearer` prefix on this endpoint):

```bash
cd /d/My_apps/Readback
READBACK_ASSEMBLYAI_API_KEY=paste-the-key-here python - <<'EOF'
import asyncio, json, os, time
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

KEY = os.environ["READBACK_ASSEMBLYAI_API_KEY"]
URL = ("wss://streaming.assemblyai.com/v3/ws"
       "?sample_rate=16000&encoding=pcm_s16le&speech_model=universal-3-5-pro")

async def main():
    t0 = time.monotonic()
    try:
        async with connect(URL, additional_headers={"Authorization": KEY},
                           open_timeout=15) as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), 15))
            await ws.send(json.dumps({"type": "Terminate"}))
            print(f"first frame after {time.monotonic()-t0:.2f}s:",
                  json.dumps({k: v for k, v in first.items() if k != "id"}))
    except InvalidStatus as exc:
        print("rejected at handshake: HTTP", exc.response.status_code)
    except ConnectionClosed as exc:
        print("closed by server:", exc.rcvd.code if exc.rcvd else "?",
              exc.rcvd.reason if exc.rcvd else "")
asyncio.run(main())
EOF
```

What it prints (measured against the live endpoint on 2026-09-03):

| Output | Meaning |
| --- | --- |
| `first frame after ~1s: {"type": "Begin", ...}` | Key works. The socket was open for about a second and closed with `Terminate`; cost is a fraction of a cent. |
| `first frame ...: {"type": "Error", ...}` or `closed by server: 1008 See Error message for details` | Key **rejected**. Both spellings were observed within ~1 s for a junk key; which one you get is a race on the server side. Fix the key before going further. |
| `rejected at handshake: HTTP 4xx` / a timeout | Network or endpoint problem, not the key. Retry. |

Note `Terminate` at the end. An abandoned streaming socket bills until the
3-hour hard close; every path in `server/` that opens one sends `Terminate`,
and so does this check.

---

## Step 2 — the secrets the server signs with

`server/config.py` ships two placeholder secrets: `READBACK_SESSION_SECRET`
(`dev-secret-not-for-production`, HMAC key for sign-in tokens) and
`READBACK_IP_HASH_SALT` (`dev-salt-not-for-production`, the salt that makes a
visitor countable without being identifiable).

**As of this change, `config.py` refuses to construct with either placeholder
— or an empty value — whenever an AssemblyAI key is present and the database is
not SQLite.** That is every deployment shape. The process exits before it
binds a port, the Render health check never passes, and the log carries:

```
RuntimeError: READBACK_SESSION_SECRET is empty or still the development placeholder.
A deployment with an AssemblyAI key and a real database must set its own value:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

(Checked on 2026-09-03: `server/auth.py` never checked this, despite a comment
in `config.py` saying it did. The comment is corrected and the check lives in
`config.py`. The message is raised as a `RuntimeError` rather than a
`ValueError` on purpose — pydantic wraps a `ValueError` in a message that
echoes the input dictionary, including the first characters of the API key,
and that message would land in the deploy log.)

`render.yaml` sets both with `generateValue: true`, so Render mints them once
and no human ever sees or copies them. If your dashboard does not offer that
option:

`>> HUMAN:` generate two values and paste them into the Render environment in
step 3:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Changing `READBACK_SESSION_SECRET` later signs every account out. That is the
intended way to sign everyone out, not a bug.

---

## Step 3 — deploy the API to Render

`render.yaml` at the repository root is a Blueprint: one web service
(`readback-api`) and one Postgres database (`readback-db`), with the connection
string wired between them.

1. <https://dashboard.render.com/> → sign in with GitHub.
2. **New → Blueprint**, pick the repository, let Render read `render.yaml`.
3. Render lists `readback-api` and `readback-db` and prompts for the one
   `sync: false` variable.
   `>> HUMAN:` paste `READBACK_ASSEMBLYAI_API_KEY` from step 1.
   (`READBACK_SESSION_SECRET` and `READBACK_IP_HASH_SALT` are generated; see
   step 2 if the prompt asks for them instead.)
4. **Apply.** The first build takes 3–5 minutes.
5. `>> HUMAN:` when it is live, copy the service URL from the top of the
   `readback-api` page — it looks like `https://readback-api-xxxx.onrender.com`.
   It is needed in steps 5 and 6 and cannot be known before this moment.

`READBACK_DATABASE_URL` is injected from the database via `fromDatabase`; you
never copy it. Render's string begins `postgres://`, which SQLAlchemy 2 rejects
— `server/db.py` rewrites it to `postgresql+psycopg://` at the one place a URL
enters the process.

### The start command, and why it is exactly that

```
python -m uvicorn server.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips="*"
```

- **`--workers 1` is a correctness requirement.** `server/main.py` keeps every
  running pipeline in a module-level dictionary and the admission windows in
  module-level counters. The `/live` WebSocket must land on the process running
  the pipeline. A second worker would answer `unknown session` for half of all
  sessions and double every limit. Do not raise it.
- **`--forwarded-allow-ips="*"` is a demo requirement.** Render terminates TLS
  and forwards the visitor's address in `X-Forwarded-For`. uvicorn only trusts
  that header from a proxy on its allow-list, whose default is `127.0.0.1` —
  and Render's proxy is not loopback. Without the flag every visitor hashes to
  the proxy's own address, and the per-IP gate (`READBACK_PER_IP_PER_HOUR=3`)
  closes for **everyone** after the third session of the hour: the fourth judge
  gets `429 per-hour limit reached for this address`. The wildcard is safe
  because the container is reachable only through Render's proxy.
- No `PYTHONPATH`, no `rootDir`: `server/` is a package at the root and
  `python -m` puts the working directory on `sys.path`. The replay fixtures are
  located from the package itself (`server/stream/replay.py` resolves
  `tests/fixtures` next to `server/`), so `tests/` must be committed and
  deployed with the code (it is committed).

### Tables are created on boot — fine for a hackathon

`server/main.py`'s lifespan runs `create_all()` before the first request:
tables, the Postgres `JSONB` variants, and the append-only audit triggers,
which `models.py` declares as dialect-dispatched DDL. There is no migration
step. If the database is unreachable, startup raises and the health check never
passes, which is the failure you want.

This is fine for the judging window. What replaces it, and when: the first
schema change after real data exists. `create_all` adds tables it does not
find and never alters one it does, so a new column on `capture` would be
silently absent in production while every SQLite test passed. The replacement
is Alembic (`alembic revision --autogenerate`, `alembic upgrade head`) run
before the process starts. Render's `preDeployCommand` is the natural place
and is documented for paid instance types; on the free plan, run it by hand
from the service Shell or fold it into `startCommand` ahead of uvicorn.

Also honest: the schema has only ever been created on **SQLite** in this
workflow. The first Render boot is the first Postgres `create_all`. The
Postgres branches of the DDL exist and are dialect-guarded; they have not been
executed here. Step 7 tests them.

### Free tier sleeps — plan for it

Render free web services spin down after ~15 minutes of no traffic. The next
request wakes the container and takes **roughly 50 seconds**.

It is worse for Readback than it was for Closeout. `web/src/lib/session.ts`
gives up on every request after **12 seconds** (`TIMEOUT_MS = 12_000`). A cold
instance therefore does not look slow; it looks broken — the first click shows
a timeout failure, and only a second attempt a minute later works.

There is one answer that works while the demo is running and does not cost
anything, and it ships in this repository.

**`.github/workflows/keep-warm.yml`** — a GitHub Actions job that pings
`/health` every 10 minutes.

Why an external caller and not the server itself: a server pinging itself
does nothing while the server is asleep, which is exactly the state that has
to be broken. The caller has to live outside Render. GitHub Actions is free
on a public repository, its scheduled runs are typically within a couple of
minutes of the cron, and this job is a single `curl` that finishes in about a
second.

**To turn it on**, once the Render URL exists (step 3):

1. In this repository on GitHub: **Settings → Secrets and variables →
   Actions → Variables → New repository variable**. Name it
   `READBACK_API`, value the Render origin (e.g. `https://readback-api-xxxx.onrender.com`).
   A variable rather than a secret: the URL is public in every screenshot of
   the app, and hiding it here changes nothing while making the workflow log
   harder to read.
2. **Actions** tab → **keep-warm** in the sidebar → **Enable workflow**
   (Actions is off by default on a new fork).
3. Click **Run workflow** once to confirm the URL is right. A green tick with
   `200 in 0.4s` in the log means it works; anything else is a real problem,
   not a schedule that has not fired yet.

Two things to know:

- **GitHub disables a scheduled workflow after 60 days of no commits.** Any
  commit resets that counter; the workflow does not resurrect itself, on
  purpose — a repository nobody is looking at should stop pinging.
- **Cron on shared runners is late sometimes.** Ten minutes is inside the
  15-minute window with margin; five would be a waste of compute for the
  same result.

Alternatives, if this ever will not do:

- **Pay.** Change `plan: free` to `plan: starter` in `render.yaml` and
  redeploy. Starter never sleeps. If the demo matters more than $7/mo, this
  is the honest answer.
- **Warm it by hand.** Two minutes before a demo, run
  `time curl -s $API/health`; it stays up through ~15 min of idle after.
- **Do NOT use Render Cron for this on the free plan** — cron is a paid
  feature, and a service pinging itself does not reliably reset the timer.

The **free Postgres instance also expires** — currently 30 days after creation,
after which it is deleted, not merely stopped. `>> HUMAN:` diarise the date, or
use Neon (appendix).

---

## Step 4 — the budget (ARCH 3.11)

Billing is socket wall-clock including silence, at $0.60/hr per socket
(`universal-3-5-pro` 0.45 + `voice_focus` 0.10 + prompting 0.05). That is
**6,000 socket-seconds per dollar**. One session is capped at 150 s; an A/B
session opens two sockets, so it costs up to 300 socket-seconds = $0.05.

`READBACK_DAILY_BUDGET_SECONDS` is the per-UTC-day ceiling across all sessions
and sockets. At 60% the server writes a `BUDGET_ALARM` audit row; at 100% it
drops to replay for the rest of the day (`/health` reports it).

| Setting | Socket-seconds/day | $/day | A/B sessions/day | Worst-case 7 days |
| --- | --- | --- | --- | --- |
| code default | 120,000 | $20 | 400 | **$140** |
| `render.yaml` | **36,000** | **$6** | **120** | **$42** |

The default is a production ceiling. A judging week does not need it: the
admission gates already allow at most 3 sessions per address per hour, and
120 two-socket sessions a day is more than a judging panel will run. At the
default, a week of steady traffic could reach $140 — more than the $50 credit
ARCH 3.11 reasons from. At 36,000 the worst week is $42 and stays inside it.

`>> HUMAN:` if the credit on the account is not $50, change the value in
`render.yaml` to `credit_dollars × 6000 ÷ 7`, rounded down. The value must
stay above 300 (one session) or `config.py` refuses to start.

**The kill switch.** Set `READBACK_REPLAY_MODE=true` in the Render dashboard
and redeploy: every session replays the recorded fixtures, no socket opens,
`/health` says `replay_mode: true`. It beats a present key by construction
(`tests/test_pipeline_e2e.py` asserts it). This is the one change to make at
2 a.m. when the bill looks wrong.

---

## Step 5 — deploy the web app to Vercel

1. <https://vercel.com/new>, import the same repository.
2. **Set Root Directory to `web`.** `vercel.json`, `package.json` and the source
   all live there, and Vercel defaults to the repository root.
3. Framework preset: **Vite** (`web/vercel.json` pins install, build and
   output, so this only sets the dashboard label).
4. Add one environment variable, for **Production, Preview and Development**:

   | Name | Value |
   | --- | --- |
   | `VITE_READBACK_API` | `https://YOUR-SERVICE.onrender.com` |

   `>> HUMAN:` this is the Render URL from step 3, **no trailing slash**.
5. **Deploy.** The build runs `tsc -b && vite build` and emits `dist/`.

### `VITE_READBACK_API`: set, empty, and absent are three different things

`web/src/lib/session.ts`:

```ts
const RAW_BASE = import.meta.env.VITE_READBACK_API;
export const apiBase =
  RAW_BASE !== undefined ? RAW_BASE.replace(/\/+$/, '')
  : import.meta.env.PROD ? '' : 'http://localhost:8000';
```

| State | `apiBase` | What happens on Vercel |
| --- | --- | --- |
| **absent** (forgot to set it) | `''` in a production build, `http://localhost:8000` under `vite dev` | Same as empty below: nothing works, visibly. It used to send sign-in and the token to `http://localhost:8000` on the *visitor's* machine; only the CSP stopped it (22 September audit). |
| **empty** (`VITE_READBACK_API=`) | `''` → same origin | `fetch('/api/…')` hits Vercel, which has no API. The SPA rewrite hands back `index.html` and the client reports `malformed`. Even with a rewrite to Render for `/api/*`, **Vercel rewrites do not carry WebSocket upgrades**, so `/api/session/{id}/live` and `/audio` would still fail. |
| **set** to the Render origin | `https://…onrender.com` | Correct. `useLiveSession.ts` turns it into `wss://…onrender.com/api/session/{id}/live` by swapping the scheme. |

Production wants **set**. "Empty means same-origin" exists for the Vite dev
proxy in `vite.config.ts`, which does forward WebSockets to `localhost:8000`;
Vercel's static hosting cannot do the same.

It is read at **build** time — Vite inlines it. Changing it later needs a
redeploy, not a restart.

### Why `vercel.json` has a rewrite

The app is a client-side router (`/`, `/login`, `/signup`, `/record`,
`/record/sessions`, `/live`, `/formats`, `/demo`, `/account`). A static host
knows about `dist/index.html` and `dist/assets/*` and nothing else. Without
`{"source": "/(.*)", "destination": "/index.html"}`, `/live` works when reached
from the sidebar and **404s on refresh or direct entry** — which is exactly how
a judge arrives at the link. Vercel checks the filesystem before rewriting, so
hashed assets still serve.

The headers: hashed assets are cached for a year (`immutable` is safe; Vite
renames them on every content change), `index.html` always revalidates so a
deploy takes effect immediately, and four security headers apply everywhere.
`X-Frame-Options: DENY` is not decoration — the consent checkbox must not be
clickjackable from a third-party frame, or the accepted version recorded in
the session row records nothing. `Permissions-Policy: microphone=(self)` is
the browser-level statement that the page's own origin is the only one that
may open the microphone.

Vercel's default Node version (22.x at time of writing) satisfies Vite 7's
requirement of Node ≥ 20.19. If the build log complains about Node, set it in
Project Settings → General.

---

## Step 6 — let the browser talk to the API (CORS)

The API accepts `fetch()` calls only from origins in `READBACK_CORS_ORIGINS`.
Until the Vercel domain is in it, the deployed page loads and then every
request fails with `offline`, and the reason is visible only in the console.

1. `>> HUMAN:` copy the Vercel production domain, e.g.
   `https://readback.vercel.app` (it is assigned at step 5; it cannot be known
   before then).
2. Replace the placeholder in `render.yaml`:
   ```
   READBACK_CORS_ORIGINS=https://readback.vercel.app,http://localhost:5173
   ```
   Comma-separated, scheme included, **no trailing slash** — an origin is
   `scheme://host[:port]` and nothing more. Commit and push (Render redeploys
   on push), or set it in the dashboard and **Save, rebuild, and deploy**.
   Committing is better: a dashboard value silently wins over the file, which
   makes the file lie about what is deployed.
3. Wait for the redeploy.

Vercel **preview** deployments get a new hostname per commit and will not
match. Demo from production, or add the exact preview hostname.

Browsers do not apply CORS to WebSocket upgrades, so a wrong list breaks
`POST /api/session/start` and leaves the sockets looking healthy. If the page
fails before a session id exists, look here first.

Verify with a preflight that echoes the origin back:

```bash
curl -s -i -X OPTIONS https://YOUR-SERVICE.onrender.com/api/session/start \
  -H "Origin: https://readback.vercel.app" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" | grep -i access-control
```

You want `access-control-allow-origin: https://readback.vercel.app`. Absent
means the origin is not in the list.

---

## Step 7 — verify it worked

Run these in order; each isolates a different failure.

```bash
API=https://YOUR-SERVICE.onrender.com
```

### 1. The service is up, and in the right shape

```bash
curl -s $API/health
```

Expect exactly these fields. Load counters and the fixture list were removed
on 22 September: unauthenticated, they told anyone the moment admission was
one session from full.

```json
{"ok": true, "live_capture": true, "replay_mode": false,
 "consent_required": true, "consent_version": "2026-09-01"}
```

- `live_capture: false` with `replay_mode: false` → the key never reached the
  process. Check the Render environment.
- `replay_mode: true` → the kill switch is on. Intended?
- `consent_required` is `true` or the deploy is wrong; there is no supported
  configuration in which it is `false` here.
- No answer at all after ~60 s → the process is not up. Read the log tail. A
  `RuntimeError: READBACK_SESSION_SECRET …` line is step 2; a psycopg
  `OperationalError` is the database; `Could not open requirements file` is
  step 0a.

### 2. Consent is enforced

```bash
curl -s -w '\n%{http_code}\n' -X POST $API/api/session/start \
  -H 'Content-Type: application/json' -d '{}'
```

Expect `403` and `consent is required before a session can start`. If this
returns `200`, stop: consent is off, and it must not be.

### 3. The database is writable, and a session can be admitted

```bash
curl -s -w '\n%{http_code}\n' -X POST $API/api/session/start \
  -H 'Content-Type: application/json' \
  -d '{"consent":{"accepted":true,"version":"2026-09-01","disclosure_played":true}}'
```

Expect `200` and a body with `session_id`, `live_capture: true`,
`cap_seconds: 150`, `sockets: 1` and `budget_remaining_seconds`. This writes
the session row and two audit rows through the Postgres schema — the first
time that schema has been exercised outside SQLite. A `500` here is the
database (read the log); a `429` is the per-IP gate, which after a fresh deploy
means the `--forwarded-allow-ips` flag is missing and everyone shares one
address.

Nothing opens a socket at this point — the socket opens when the browser
connects `/api/session/{id}/audio` — so this costs nothing. End the session
anyway so the slot is released:

```bash
curl -s -X POST $API/api/session/PASTE-THE-SESSION-ID/stop \
  -H 'Content-Type: application/json' -d '{"delete": true}'
```

Expect `{"ok": true, "deleted": true}`. Deleting proves the cascade works on
Postgres, which the consent story depends on.

### 4. The whole thing, in a browser, with a microphone

1. Open the Vercel URL. The landing page renders.
2. Go to `/live`. **Hard-refresh (Ctrl+Shift+R).** It must reload `/live`, not
   a 404 — that is the rewrite from step 5.
3. Read the disclosure, tick the consent box, click Start. The browser asks for
   the microphone. Both must happen, in that order: the checkbox is consent,
   the browser prompt is not.
4. Read a container number aloud — `MSKU 4158005` is the fixture value.
   Watch the rack. The agent should write it, silently or after one question.
5. Click Stop and delete. The row disappears.
6. In the Render log tail, the session should show one `Terminate` sent. If
   the log shows a socket without a `Terminate`, that socket is billing until
   the 3-hour hard close — stop the service and find out why before the next
   demo.

The `Terminate` line in step 6 is the check that nothing is still running.
A pipeline that outlives its browser tab is a pipeline that spends money.

### 5. Client addresses (READBACK_TRUSTED_PROXY_HOPS)

Every per-address limit -- sign-in, sign-up, demo replay, session admission --
keys on the address `server/ratelimit.py:client_ip` picks out of
`X-Forwarded-For`. `render.yaml` assumes one proxy appends to that header.
Measure it instead of trusting it:

1. From one network (Wi-Fi), fail sign-in on purpose until the API answers
   `429`.
2. Immediately, from a different network (a phone hotspot), try once.
   - It answers normally → addresses are distinct. `1` is right.
   - It is also `429` → every visitor is being counted as one address: a
     second proxy is appending. Set `READBACK_TRUSTED_PROXY_HOPS=2`, redeploy,
     repeat.
3. Never set it higher than the count you measured. One too many makes the
   client-written entry the trusted one, and every per-address limit becomes
   bypassable with a single header.

---

## What a person must do by hand — checklist

None of this can be scripted from here. Every item needs a browser, an
account, or a value that does not exist until something else is deployed.

- [x] `requirements.txt` and `requirements.lock` are both in the repository
      (step 0a). If you change a dependency, regenerate the lock before
      pushing, or the build installs the resolution it already had.
- [ ] Confirm `.env` and `*.db` are not staged; push to GitHub (step 0b, 0c)
- [ ] Create an AssemblyAI account, copy the key, run the socket check (step 1)
- [ ] Generate two secrets only if Render does not offer `generateValue` (step 2)
- [ ] Apply the Blueprint; paste `READBACK_ASSEMBLYAI_API_KEY` at the prompt (step 3)
- [ ] Copy the assigned Render URL (step 3) — **cannot be pre-filled; the
      hostname does not exist before the first deploy**
- [ ] Set the daily budget to match the account's actual credit (step 4)
- [ ] Create the Vercel project with **Root Directory = `web`** (step 5)
- [ ] Set `VITE_READBACK_API` to the Render URL — set, not empty (step 5)
- [ ] Put the Vercel origin into `READBACK_CORS_ORIGINS`; redeploy the API (step 6)
- [ ] Turn on the keep-warm workflow: Actions tab → Enable, then set
      the `READBACK_API` repository variable to the Render URL (step 3,
      "Free tier sleeps"). Without this, the first visitor after 15 min of
      idle sees a timeout.
- [ ] Diarise the free Postgres expiry, or use Neon (step 3)
- [ ] Sign up in the deployed app, then in the Render **Shell** run
      `python -m server.admin_cli grant <your email>` -- the only way to open
      `/admin` (docs/ADMIN.md)
- [ ] Measure `READBACK_TRUSTED_PROXY_HOPS` (step 7, "Client addresses")

Circular by nature: **Render must exist before Vercel can be configured, and
Vercel must exist before CORS can be finished.** Expect two deploys of the API.

---

## Appendix — Postgres on Neon instead

Neon's free tier does not expire after 30 days.

1. Create a project at <https://neon.tech> and copy the **pooled** connection
   string (`-pooler` in the hostname; Neon suspends idle computes and the
   pooler handles the wake-up).
2. In `render.yaml`, delete the `databases:` block and replace the
   `READBACK_DATABASE_URL` entry with:
   ```yaml
   - key: READBACK_DATABASE_URL
     sync: false
   ```
3. `>> HUMAN:` paste the string into the Render dashboard.

`server/db.py` rewrites Neon's `postgresql://` to `postgresql+psycopg://` and
keeps `?sslmode=require`. `pool_pre_ping` is already on for every non-SQLite
URL, so the first request after a suspend reconnects instead of failing.

---

## Appendix — assumptions not verified without an account

Everything above that was measurable from this machine was measured (the
streaming handshake, the config refusal, the test suite, the client timeout,
the URL derivation). These were not:

| Claim | Basis | How to check |
| --- | --- | --- |
| Render free web services proxy WebSocket upgrades | Render documentation; Closeout ran HTTP only | Step 7.4 — the `/live` socket opens, or the console shows an error on `wss://` |
| Free instances sleep after ~15 min and wake in ~50 s | Closeout's measured experience, carried over | `time curl $API/health` after 20 min idle |
| Free Postgres expires 30 days after creation, 1 GB | Render pricing page at the time Closeout deployed | The database page in the dashboard shows the date |
| `plan: free` / `plan: starter` are the current plan names, starter ≈ $7/mo | Render's Blueprint reference | The Blueprint apply screen lists the plans it accepts |
| `generateValue: true` is accepted for `envVars` | Render's Blueprint reference | The apply screen either shows the two values as generated or prompts for them (step 2 fallback) |
| Render's proxy puts the client address first in `X-Forwarded-For` | Render documentation; `server/ratelimit.py` already assumes it | After deploy, two sessions from two networks must not share a `429` budget |
| `preDeployCommand` needs a paid instance | Render documentation | Only matters once Alembic exists |
| Vercel's default Node satisfies Vite 7 (≥ 20.19) | Vercel's current default is 22.x | The first build log |
| The $50 credit figure | ARCH 3.11 uses it | The AssemblyAI billing page |
| Postgres `create_all` including the audit triggers succeeds | The DDL is dialect-guarded in `models.py`; only SQLite has run it | Step 7.3 writes and deletes a row |

---

## Appendix — file reference

| File | Purpose |
| --- | --- |
| `render.yaml` | Blueprint: API service + Postgres, env vars, health check, budget, kill switch |
| `web/vercel.json` | Static build, SPA rewrite, cache and security headers |
| `.env.example` | Every `READBACK_` variable with its reason; no values |
| `web/.env.example` | `VITE_READBACK_API` for local development |
| `server/config.py` | Settings; refuses placeholder or empty secrets on a deployment shape |
| `server/db.py` | URL normalisation to psycopg 3, Postgres pool settings |
| `requirements.txt` | The nine direct dependencies, each with its reason |
| `requirements.lock` | All 29 packages with artefact hashes; what Render installs, with `--require-hashes` |
