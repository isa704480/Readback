# Deploying Closeout

API on Render, web on Vercel, Postgres on Render (Neon alternative at the end).

This document is written to be followed, not skimmed. Where a step needs a
human — a browser, a card, a copy-paste of a value that does not exist yet —
it says so plainly. Nothing here is automated for you.

Budget about 40 minutes the first time. Most of it is waiting for builds.

---

## The one constraint that shapes everything

**The API must be publicly reachable over HTTPS.**

Closeout is not a normal front-end/back-end split. When a technician starts a
session, our server hands AssemblyAI a set of *server-side tool definitions* —
each one an HTTPS URL on our API, with a scoped bearer token in its headers.
The voice agent then calls those URLs **from AssemblyAI's own infrastructure**.
The technician's browser is not in that path. Neither is your laptop.

That means `CLOSEOUT_PUBLIC_BASE_URL` must be a hostname AssemblyAI's servers
can resolve and reach. `http://localhost:8000` can never work in production:
on their machines, `localhost` is *their* loopback. The agent would connect,
greet the technician, and then silently fail to write a single field — the
worst possible failure mode, because it looks like it is working.

The value is built into tool URLs in `backend/app/voice/tools.py`:

```python
base = get_settings().closeout_public_base_url.rstrip("/")
...
"url": f"{base}/api/tools/{tool['name']}"
```

You cannot set this before the first deploy, because Render assigns the
hostname. The sequence is therefore: **deploy once with a placeholder, copy the
real URL, set it, redeploy.** That is not a mistake in the instructions; it is
inherent to the platform. Step 4 below.

For local development, the same constraint applies — use an ngrok tunnel and
set `CLOSEOUT_PUBLIC_BASE_URL` to the `https://….ngrok-free.app` URL.

---

## Step 0 — repository hygiene (do this first)

Two things in the working tree will bite you if you skip them.

**`web/` contains its own empty git repository.** `web/.git` exists, has zero
commits and no remote. If you `git init` at the project root and commit, git
will treat `web/` as an embedded repository and silently exclude every file
inside it. You would push a repo whose `web/` directory is empty, and the
Vercel build would fail with "no such file or directory: package.json" — with
nothing in the logs pointing at the cause.

Check for it, then remove it:

```bash
cd /d/My_apps/Closeout
ls -d web/.git && echo "nested repo present -- remove it"
rm -rf web/.git
```

(Nothing is lost: that repo has no commits and no remote. Verify for yourself
first with `git -C web log --oneline` — it will say the branch has no commits.)

**The project root is not a git repository yet.** Render and Vercel both deploy
from a git host. Initialise, then push to GitHub:

```bash
cd /d/My_apps/Closeout
git init -b main
git add .
git status          # confirm web/src/** is listed. If it is not, step 0 above was skipped.
git commit -m "Closeout: deployment configuration"
gh repo create closeout --private --source=. --push
```

Before committing, confirm no secrets are staged. `.gitignore` already covers
`.env` and `*.db`, but check rather than trust:

```bash
git ls-files | grep -E '\.env$|\.db$' && echo "STOP -- secrets staged" || echo "clean"
```

---

## Step 1 — get an AssemblyAI API key (manual, browser)

Nobody can do this for you; it needs an account and a browser.

1. Sign up at <https://www.assemblyai.com/>.
2. Open the dashboard and copy the API key.
3. Confirm your account has **Voice Agent** access and credit on it. The
   transcription key and the voice-agent entitlement are the same key, but the
   entitlement is not on every plan. If it is missing, `/api/session/start`
   will return `voice_unavailable` forever and no amount of config will fix it.

Keep the key in a password manager. Do not put it in a file in this repo. It
goes into the Render dashboard by hand in step 3, and nowhere else.

Sanity-check the key before you deploy — this is the same call the API makes:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer YOUR_ASSEMBLYAI_KEY" \
  "https://agents.assemblyai.com/v1/token?expires_in_seconds=120&max_session_duration_seconds=420"
```

`200` means the key works. Anything else means fix this before going further —
a bad key surfaces later as `voice_unavailable`, which looks like a network
problem and is not.

---

## Step 2 — generate `CLOSEOUT_TOOL_SECRET`

This signs two things: the short-lived per-session tool tokens that authorise
AssemblyAI to write to one specific report, and the office session tokens. If
it leaks, anyone can mint a token and write to any report.

Generate a fresh one. Do not reuse the development value, and do not use the
one in `backend/.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the output. It goes into the Render dashboard in step 3 and nowhere else.

The app refuses to start sessions while this is unset or still `change-me`:

```json
{"error": "misconfigured", "message": "Server not configured: CLOSEOUT_TOOL_SECRET is not configured"}
```

That refusal is deliberate. An unsigned tool token would be a blank cheque.

---

## Step 3 — deploy the API to Render

`render.yaml` at the project root is a Blueprint: it declares the web service
and the Postgres database together and wires the connection string between
them.

1. Go to <https://dashboard.render.com/> and sign in with GitHub.
2. **New → Blueprint**, select the repository, and let it read `render.yaml`.
3. Render will detect `closeout-api` and `closeout-db`, and will prompt for the
   two variables marked `sync: false`. Paste them now:
   - `ASSEMBLYAI_API_KEY` — from step 1
   - `CLOSEOUT_TOOL_SECRET` — from step 2
4. **Apply**. First build takes 3–5 minutes (installing `psycopg[binary]` and
   `uvicorn[standard]` dominates).

`DATABASE_URL` is injected automatically from the database via `fromDatabase`.
You never copy that string by hand.

**Tables are created automatically.** `backend/app/main.py` has:

```python
@app.on_event("startup")
def _startup() -> None:
    init_db()                     # Base.metadata.create_all(engine)
    seed.ensure_organization()
```

so `create_all` runs on every boot, before the first request is served. There
is no migration step and no separate init command in the start command. This is
confirmed behaviour, not an assumption — it is why `healthCheckPath: /health`
is safe to rely on: if the database were unreachable, startup would raise and
the health check would never pass.

If you ever want to run it explicitly — say, to tell "database unreachable"
apart from "app crashed on import" — open **Render → closeout-api → Shell**:

```bash
python manage.py check      # resolve URL, connect, list tables
python manage.py initdb     # create_all + seed, then report
python manage.py config     # resolved settings, secrets redacted
```

`manage.py config` exits non-zero and names the problem when the deployment is
misconfigured, including the localhost trap in step 4.

### Free tier sleeps — plan for it

Render free web services spin down after ~15 minutes of no traffic. The next
request wakes the container and takes **roughly 50 seconds**. To a judge
clicking "Start" that is indistinguishable from a broken app.

Pick one:

- **Warm it by hand.** Two minutes before the demo:
  ```bash
  time curl -s https://YOUR-SERVICE.onrender.com/health
  ```
  Wait for `{"status":"ok"}`. It then stays up through ~15 min of idle.
- **Keep it warm.** Point any free uptime monitor at `/health` every 10
  minutes. Do not use Render Cron for this on the free plan — cron is a paid
  feature, and a service pinging itself does not reliably reset the timer.
- **Pay.** Change `plan: free` to `plan: starter` in `render.yaml` and
  redeploy. Starter never sleeps. If the demo matters more than $7/mo, this is
  the honest answer.

The **free Postgres instance also expires** — currently 30 days after creation,
after which it is deleted, not merely stopped. For anything beyond a hackathon
weekend, upgrade the database plan or use Neon (appendix).

---

## Step 4 — set `CLOSEOUT_PUBLIC_BASE_URL` to the real Render URL

**This is the step people skip, and it is the step that breaks the demo.**

`render.yaml` ships a placeholder (`https://closeout-api.onrender.com`). Unless
your service happened to claim exactly that name, it is wrong right now.

1. Render dashboard → `closeout-api`. Copy the URL at the top of the page —
   something like `https://closeout-api-a1b2.onrender.com`.
2. Either edit `render.yaml` and push:
   ```bash
   cd /d/My_apps/Closeout
   # edit the CLOSEOUT_PUBLIC_BASE_URL value, no trailing slash
   git commit -am "Point CLOSEOUT_PUBLIC_BASE_URL at the deployed API"
   git push
   ```
   or set it in **Environment** in the dashboard and click **Save, rebuild, and
   deploy**. Committing it is better: the dashboard value silently wins over
   the file, which makes the file lie about what is deployed.
3. Wait for the redeploy, then confirm it took:
   ```bash
   curl -s https://YOUR-SERVICE.onrender.com/health
   ```

There is no way to verify this value from outside except by running a real
session (step 7) — the tool URLs are only assembled after AssemblyAI issues a
token. If tools silently do nothing during a session, this is the first thing
to check.

---

## Step 5 — deploy the web app to Vercel

1. <https://vercel.com/new>, import the same repository.
2. **Set Root Directory to `web`.** This is not optional and not auto-detected
   correctly for this layout — `vercel.json`, `package.json` and the source all
   live under `web/`, and Vercel defaults to the repository root.
3. Framework preset: **Vite** (`web/vercel.json` already pins the build, so
   this only affects the dashboard label).
4. Add an environment variable, for **Production, Preview and Development**:

   | Name | Value |
   | --- | --- |
   | `VITE_CLOSEOUT_API` | `https://YOUR-SERVICE.onrender.com` |

   No trailing slash. This is read at **build** time, not run time — Vite
   inlines it into the bundle. Changing it later requires a **redeploy**, not
   just a restart. If you forget it, the app falls back to
   `http://localhost:8000` (see `web/src/lib/session.ts`), and every call from
   the deployed site fails with a mixed-content or connection error.
5. **Deploy.** The build runs `tsc -b && vite build` and emits `dist/`.

### Why `vercel.json` has a rewrite

```json
"rewrites": [{ "source": "/(.*)", "destination": "/index.html" }]
```

The app is a client-side router (`BrowserRouter`, routes `/`, `/login`,
`/signup`, `/office`, `/app`). A static host knows about `dist/index.html` and
`dist/assets/*` and nothing else. Without the rewrite, `/office` and `/app`
work when reached by an in-app link — React Router handles those without a
network request — and **404 on refresh or direct entry**, because the browser
actually asks the server for a file at that path.

That is not hypothetical here: the office view links technicians to
`/app?report=…`, which is a URL people open cold, paste into phones, and
refresh. Without the rewrite that link is broken for exactly the audience it
exists for.

The rewrite hands `index.html` to any path that is not a real file — Vercel
checks the filesystem before applying rewrites, so `/assets/index-abc123.js`
still serves the real asset. React Router then reads the URL and renders the
right screen. The query string survives the rewrite untouched.

The `headers` block caches hashed assets for a year (`immutable` is safe —
Vite renames them on every content change) while forcing `index.html` to
revalidate, so a deploy takes effect immediately instead of leaving people on a
stale bundle pointing at old asset names.

---

## Step 6 — let the browser talk to the API (CORS)

The API only accepts browser origins listed in `CORS_ORIGINS`. Until you add
the Vercel domain, the deployed site loads and then fails every request, with
the real reason visible only in the browser console.

1. Copy your Vercel production domain, e.g. `https://closeout.vercel.app`.
2. Update `CORS_ORIGINS` in `render.yaml` (or in the Render dashboard):

   ```
   https://closeout.vercel.app,http://localhost:5173
   ```

   Comma-separated, scheme included, **no trailing slashes** — an origin is
   `scheme://host[:port]` and nothing more. `config.py` strips surrounding
   whitespace, so spaces after commas are fine.
3. Redeploy the API.

Note: **Vercel preview deployments get a new hostname per commit** and will not
match this list. If you demo from a preview URL, add that exact hostname too,
or demo from production.

Verify from a shell — a preflight that echoes your origin back is the proof:

```bash
curl -s -i -X OPTIONS https://YOUR-SERVICE.onrender.com/api/auth/login \
  -H "Origin: https://closeout.vercel.app" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" | grep -i access-control
```

You want `access-control-allow-origin: https://closeout.vercel.app`. If the
header is absent, the origin is not in the list.

---

## Step 7 — verify it worked

Run these in order. Each one isolates a different failure.

Set the host once:

```bash
API=https://YOUR-SERVICE.onrender.com
```

### 1. The service is up

```bash
curl -s $API/health
```

Expect exactly:

```json
{"status":"ok"}
```

If this hangs for ~50 seconds first, that is the free tier waking up, not a
fault. If it never answers, the service failed to boot — check the Render logs;
a database that cannot be reached raises during startup, so the health check
never passes.

### 2. The database is writable

Signup is the cheapest end-to-end write: it creates an organization, a
technician and a user in one transaction.

```bash
curl -s -X POST $API/api/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","name":"Demo Tech","company":"Demo HVAC","password":"demo-password"}'
```

Expect `200` and a body shaped like:

```json
{
  "token": "eyJhbGciOi…",
  "account": {
    "id": "…",
    "name": "Demo Tech",
    "email": "demo@example.com",
    "role": "owner",
    "organization": {"id": "…", "name": "Demo HVAC", "trade": "hvac", "labor_rate": 42.0, "currency": "USD"}
  }
}
```

Run it a second time and you should get `409` with
`{"error":"email","message":"That email already has an account. Sign in instead."}`.
That second call proves more than the first: the row **persisted**, so the
database is real and not an ephemeral filesystem.

A `500` here means `DATABASE_URL`. Check `manage.py check` in the Render shell.

### 3. Voice is configured

```bash
curl -s -w '\n%{http_code}\n' -X POST $API/api/session/start \
  -H 'Content-Type: application/json' -d '{}'
```

Read the `error` field, not just the status. These are measured behaviours, not
guesses:

| Response | Status | Meaning |
| --- | --- | --- |
| `{"error":"misconfigured","message":"Server not configured: CLOSEOUT_TOOL_SECRET is not configured"}` | 500 | Step 2 not done. The tool secret is checked **first**, so this masks a missing API key. |
| `{"error":"misconfigured","message":"ASSEMBLYAI_API_KEY is not set…"}` | 500 | Step 1/3 not done — the key never reached Render. |
| `{"error":"voice_unavailable","message":"Client error '401 Unauthorized'…"}` | 502 | Key is set but **rejected** by AssemblyAI. Wrong key, or no voice-agent entitlement. |
| `{"error":"voice_unavailable","message":"…timed out…"}` | 502 | Key is set; AssemblyAI unreachable. Transient — retry. |
| A JSON body with `session_id`, a `wss://` URL and a tool config | 200 | Working. |

**The thing to confirm is that you have stopped seeing `misconfigured`.**
`misconfigured` is *our* server admitting it lacks configuration;
`voice_unavailable` means our config is complete and the failure is on the
other side of the wire. Crossing from the first to the second is the signal
that steps 1–3 landed.

On a `200`, check the public base URL made it into the tool URLs — this is the
only place step 4 is externally observable:

```bash
curl -s -X POST $API/api/session/start -H 'Content-Type: application/json' -d '{}' \
  | grep -o 'https://[^"]*/api/tools/[a-z_]*' | head -3
```

Every URL must start with your Render hostname. If any says `localhost`, step 4
did not take effect and no tool call will ever reach you.

### 4. The whole thing, in a browser

1. Open the Vercel URL. The landing page renders.
2. Sign up, land on `/office`, see the seeded HVAC jobs.
3. Click through to a job — the URL becomes `/app?report=…`.
4. **Hard-refresh that page (Ctrl+Shift+R).** It must reload the technician
   screen, not a 404. This is the rewrite from step 5 doing its job; it is the
   single easiest deployment mistake to ship without noticing.
5. Start a session and speak. Watch the report fields fill in. If the agent
   talks but nothing is ever recorded, `CLOSEOUT_PUBLIC_BASE_URL` is wrong —
   go back to step 4.

---

## What a person must do by hand — checklist

None of this can be scripted from here. Every item needs a browser, an account,
or a value that does not exist until something else has been deployed.

- [ ] Remove the nested `web/.git` (step 0)
- [ ] Create the git repository and push it to GitHub (step 0)
- [ ] Create an AssemblyAI account and copy the API key (step 1)
- [ ] Confirm the key has voice-agent access and credit (step 1)
- [ ] Generate `CLOSEOUT_TOOL_SECRET` and store it in a password manager (step 2)
- [ ] Create the Render account, connect GitHub, apply the Blueprint (step 3)
- [ ] Paste both `sync: false` secrets into the Render prompt (step 3)
- [ ] Copy the assigned Render URL and set `CLOSEOUT_PUBLIC_BASE_URL`, then
      redeploy (step 4) — **cannot be pre-filled; the hostname does not exist
      before the first deploy**
- [ ] Create the Vercel project with **Root Directory = `web`** (step 5)
- [ ] Set `VITE_CLOSEOUT_API` on Vercel to the Render URL (step 5)
- [ ] Add the Vercel origin to `CORS_ORIGINS` and redeploy the API (step 6)
- [ ] Decide how to handle cold starts before any demo (step 3)
- [ ] Diarise the free Postgres expiry, or upgrade the plan (step 3)

Circular by nature: **Render must exist before Vercel can be configured, and
Vercel must exist before CORS can be finished.** Expect two redeploys of the
API. That is the platform, not a flaw in these instructions.

---

## Database portability — what was changed and why

`backend/app/db.py` now normalises the connection URL before building the
engine. Without this the API cannot boot on Render at all. Two independent
breakages, both invisible locally:

**1. `postgres://` is not a SQLAlchemy 2 scheme.** Render (and Heroku) hand out
connection strings beginning `postgres://`. SQLAlchemy 1.3 accepted that alias;
SQLAlchemy 2 removed it. Verified against the pinned `sqlalchemy==2.0.36`:

```
postgres://u:p@h:5432/d      -> NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres
postgresql://u:p@h:5432/d    -> OK, dialect PGDialect_psycopg2
postgresql+psycopg://…       -> OK, dialect PGDialect_psycopg
```

**2. A bare `postgresql://` selects the wrong driver.** It parses, but resolves
to the **psycopg2** dialect. `requirements.txt` pins `psycopg[binary]==3.2.3`,
which is psycopg **3** and imports as `psycopg`; psycopg2 is not installed on
Render. So the fixed-prefix form would still have died at `create_engine` with
`ModuleNotFoundError: No module named 'psycopg2'`.

This one hides on a developer machine that happens to have psycopg2 installed
system-wide — as this one does. It would have failed only in production.

Both forms are now rewritten to `postgresql+psycopg://`, naming the driver we
actually ship. A URL that already specifies a driver (`+psycopg`, `+psycopg2`,
`+asyncpg`) is left alone, and `sqlite://` is untouched, so local development
is unaffected.

`pool_pre_ping` and `pool_recycle=300` were added for Postgres only. Managed
providers cull idle connections; without pre-ping the first request after a
quiet period fails on a dead connection instead of transparently reconnecting —
which on a sleeping free tier is *every* first request.

Check the resolved URL and driver on any environment:

```bash
cd backend && python manage.py check
```

---

## Appendix — Postgres on Neon instead

Neon's free tier does not expire after 30 days, which makes it the better
choice for anything that should outlive the hackathon.

1. Create a project at <https://neon.tech> and copy the pooled connection
   string. It looks like:
   `postgresql://user:pass@ep-xyz-pooler.region.aws.neon.tech/neondb?sslmode=require`
2. In `render.yaml`, delete the `databases:` block and replace the `DATABASE_URL`
   entry with `sync: false`:

   ```yaml
   - key: DATABASE_URL
     sync: false
   ```

3. Paste the string into the Render dashboard.

The normaliser rewrites Neon's `postgresql://` to `postgresql+psycopg://`
automatically, and `?sslmode=require` is preserved. Use the **pooled** endpoint
(`-pooler` in the hostname); Neon scales to zero, and the pooler handles
reconnection to a suspended compute far better than a direct endpoint does.

---

## Appendix — file reference

| File | Purpose |
| --- | --- |
| `render.yaml` | Blueprint: API service + Postgres, env vars, health check |
| `web/vercel.json` | Static build + SPA rewrite + cache headers |
| `backend/manage.py` | `check` / `initdb` / `config` for the Render shell |
| `backend/app/db.py` | URL normalisation and Postgres pool settings |
| `.env.example` | Local development template |
| `web/.env.example` | `VITE_CLOSEOUT_API` for local development |
