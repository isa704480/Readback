# Salvage from Closeout

Closeout was the previous direction (voice job closeout for field service). It
was abandoned after the competitor roster showed the position was the most
contested in the field — five teams building the same refusal mechanism, and
one, Talos Tech, carrying the identical framing.

These files survived because they are expensive to rewrite and independent of
that product's domain:

| file | what it is |
|---|---|
| `report_pdf.py` | ReportLab PDF renderer. Note the `KeepTogether` trap documented inside: a nested `KeepTogether` measures as 16 million points and breaks to a fresh page every time. |
| `ratelimit.py` | Fixed-window limiter, per-IP and per-key, with the reasoning for why login needs both. |
| `password.py` | PBKDF2 policy plus the Have I Been Pwned k-anonymity breach check — only the first five hex characters of the SHA-1 leave the process. |
| `render.yaml`, `vercel.json`, `DEPLOY.md` | Deploy config. `DEPLOY.md` records that `postgres://` AND bare `postgresql://` both fail against psycopg 3 — the second one silently, and only in production. |

Nothing here is wired into Readback. Take what is useful and delete the rest.
