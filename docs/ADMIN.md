# The platform admin panel

`/admin` in the web app, `/api/admin/*` on the server. For the people who run
the deployment, not for the organisations that use it.

## Who gets in

A signed-in account with a row in `platform_admin`. That row is written in one
place only:

```bash
python -m server.admin_cli grant ops@yourcompany.com
python -m server.admin_cli list
python -m server.admin_cli revoke ops@yourcompany.com
```

Run it where the server runs (Render: the service's **Shell** tab), against the
same `READBACK_DATABASE_URL`. Sign up through the app first; the CLI refuses an
address with no account.

Why a CLI and not an email allowlist in configuration: sign-up is open and email
is never verified. "This address is an admin" would make whoever registered it
first the operator of every tenant. A shell on the server is a credential an
attacker does not get by filling in a form. `tests/test_admin.py` fails if any
module other than the CLI constructs a `PlatformAdmin`.

Everyone else -- every organisation's own owner included -- gets **404** from
every admin route, so a tenant cannot tell the panel exists. The Admin link in
the rail is absent, not disabled, for them.

## What it does

| tab | reads | writes (all audited as `admin:<user id>`) |
|---|---|---|
| Overview | tenants, users, sessions 24 h / 7 d, running vs capacity, spend vs daily budget, 7-day quality, last benchmark | -- |
| AI quality | traffic metrics by window (1-90 days) and source; the benchmark | run the benchmark |
| Organisations | 7-day sessions and captures, spend today, own budget, last session | suspend (with a reason), reinstate, set or clear the organisation's daily budget |
| Users | email, organisation, role, last sign-in, operator flag | disable, enable |
| Live | sessions running now, how long, whether a microphone is attached | force-stop |
| Audit log | the append-only log, filterable by action or `admin.` prefix, paged | -- |
| Controls | the two runtime switches | pause live capture, pause sign-ups |
| System | environment, database, whether the AssemblyAI key is present (never its value), limits, CORS | -- |

## What each switch actually changes

Stored settings that nothing reads are worse than no settings. Each one is
enforced in the code path it constrains:

- **Suspend an organisation** (`Organisation.active = false`). `POST
  /api/session/start` answers 403 `organisation_suspended`, after the consent
  gate and before any limit is spent; `POST /api/demo/replay` refuses too, so
  suspending the demo tenant stops anonymous replays. Any session it has
  running is stopped at the moment of suspension.
- **Organisation daily budget** (`Organisation.daily_budget_seconds`). When the
  organisation's own socket-seconds today reach it, its new sessions run the
  recorded fixtures instead of opening a socket -- the same fallback the
  deployment budget uses -- with `replay.entered {reason: organisation_budget}`
  in the audit log. Empty means "no ceiling of its own"; the deployment's still
  applies.
- **Pause live capture.** Every new session drops to replay, reason
  `live_paused`. Running sessions are not touched; stop them from Live.
- **Pause sign-ups.** `POST /api/auth/signup` answers 403 `signups_paused`
  before any password work. Existing accounts keep working.
- **Disable a user.** Their token is rejected on the next request
  (`auth.resolve_user` re-reads `User.active` every time). You cannot disable
  yourself or another operator -- revoke an operator with the CLI.

Both organisation fields were in the schema from the start and were enforced
nowhere until the panel could set them.

## How right the agent is

`server/quality.py`. Two instruments, because live calls have no ground truth.

**Traffic metrics** -- what a voice-agent team watches in production:

| metric | means |
|---|---|
| written without asking | of committed captures, the share written without a word |
| repaired in silence | of committed captures, the share the format corrected without asking |
| asked a question | of all captures, the share where the agent spoke |
| handed to a person | of all captures, the share the agent gave up on |
| time to write | median and p95 from the identifier's last word to the commit |
| **question necessity** | see below |

**Question necessity** is the one closest to a real accuracy signal. When the
agent asks about one character and a person answers, that answer *is* the truth
for that position. If it differs from what the recogniser heard, the question
prevented a wrong write ("needed"); if it matches, the interruption was
unnecessary. The needed share is the precision of the agent's doubt. It says
nothing about mishearings the agent did *not* ask about -- that is what the
benchmark and `docs/EXPERIMENT.md` are for.

**Benchmark** -- every fixture in `tests/fixtures/` carries `truth`. The
benchmark replays each through the same runner the microphone uses, with a
simulated person who answers every question correctly, and scores:

- correct: the value written equals the truth, or nothing is written when the
  recording holds no identifier;
- silent-wrong: a capture written without asking that is not the truth -- the
  failure this product exists to prevent;
- questions at the right position, where the fixture says where one belongs.

Today: 8 of 8 correct, 0 silent-wrong, 1 of 1 question at the right position.
`test_the_benchmark_can_fail` answers every question wrong and checks the
score drops -- an instrument that cannot report a failure measures nothing.
Eight recordings are a regression check, not a statistical estimate; the
~12M-capture measurement in `docs/EXPERIMENT.md` is that.

## What it deliberately does not do

- **No impersonation.** "Log in as this user" is standard in SaaS admin panels
  and is the single most abused operator feature. Everything an operator needs
  to see about a tenant is in the organisation drill-down, without becoming them.
- **No billing screen.** Readback has no payments; spend is socket-seconds
  against a budget, and that is on Overview and per organisation.
- **No deletion of organisations or users.** Suspend and disable are reversible
  and audited; deletion is a data-retention decision (`server/purge.py`), not a
  button.
- **No granting admin from the panel.** See "Who gets in".
