"""The HTTP perimeter: what every request passes through before a route sees it.

Five things, installed in one call so their order is written down in one place
rather than implied by where decorators happen to sit in a 2,000-line module:

  security headers   innermost -- decorates whatever the route answered
  body bound         caps bytes RECEIVED, not bytes declared
  CORS               outermost, so even a 413 is readable cross-origin
  flat 422           field names only, never the submitted value
  flat HTTPException one error shape for every failure

`install` is the only public entry point. Nothing here knows about sessions,
captures or the database.
"""

from __future__ import annotations

import json
from typing import Any, Final

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# The largest body any route here has a use for. The biggest legitimate one is
# a 500-row catalogue PUT; 1 MiB is generous for that and small enough that an
# unauthenticated POST cannot make the process buffer a large body before a
# field constraint could refuse it -- a body is read in full before any field is
# validated, so this is the only place the size can actually be bounded.
MAX_BODY_BYTES: Final = 1_048_576


async def _security_headers(request: Request, call_next):
    """The headers a token-bearing API should send, which it sent none of.

    HSTS only over HTTPS: sending it on a plain-HTTP development origin is
    ignored by browsers at best and pins localhost to HTTPS at worst. No CSP
    here -- this origin serves JSON, never a document; the SPA's own CSP is in
    web/vercel.json.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


async def _flat_validation_errors(request: Request,
                                  exc: RequestValidationError) -> JSONResponse:
    """A 422 in the same two-key shape as every other failure, and WITHOUT the
    submitted value.

    FastAPI's default body echoes `input` verbatim, so a signup or login whose
    password failed a length constraint answered with the plaintext password --
    into the client's console, any error tracker and any log that keeps bodies.
    The field names are enough to fix the request; the value was never ours to
    repeat.
    """
    where = [".".join(str(p) for p in e.get("loc", ())[1:]) or "body"
             for e in exc.errors()]
    return JSONResponse(status_code=422, content={
        "error": "invalid_request",
        "message": "Some of those details were not accepted: " + ", ".join(
            dict.fromkeys(where)) + ".",
    })


async def _flat_errors(request: Request, exc: HTTPException) -> JSONResponse:
    """Error bodies the client can actually read.

    FastAPI wraps every detail in {"detail": ...}. web/src/lib/session.ts reads
    `error` and `message` at the TOP level, and PasswordStrength reads
    `password_check` there too -- so a dict detail is emitted flat, and a plain
    string one is given the same two keys while keeping `detail` for anything
    that still expects it. One shape for every failure, or each screen invents
    its own unwrapping and they drift.
    """
    if isinstance(exc.detail, dict):
        body: dict[str, Any] = dict(exc.detail)
    else:
        body = {
            "error": "http_error",
            "message": str(exc.detail),
            "detail": exc.detail,
        }
    return JSONResponse(status_code=exc.status_code, content=body,
                        headers=dict(exc.headers or {}))


def bad_request(error: str, message: str) -> HTTPException:
    """Flat body, same two keys as every other failure. See `_flat_errors`; raise it."""
    return HTTPException(status_code=400, detail={"error": error, "message": message})


class _BodyTooLarge(Exception):
    """Raised out of the wrapped `receive` the moment the running total passes
    the cap, so no handler ever holds the rest of the body."""


class BoundBody:
    """Refuse an oversize body with the same flat shape as every other failure.

    Content-Length is a claim, not a fact. The first version of this guard read
    only the header, and its docstring promised more than that: a body sent
    chunked, with no Content-Length at all, was buffered in full and parsed
    (measured 22 September -- 1.1 MB reached the handler, which answered with
    its own field error). So the bound is on bytes actually received: the ASGI
    `receive` is wrapped and counts every `http.request` chunk as it arrives.
    The header check stays in front of it as the cheap early exit.

    A raw ASGI class rather than `@app.middleware("http")`: that decorator
    hands the handler a Request whose body stream it does not own, so it can
    see the header and nothing after it.
    """

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _refuse(self, send) -> None:
        payload = json.dumps({
            "error": "body_too_large",
            "message": f"the request body must be at most {self.max_bytes} bytes.",
        }).encode("utf-8")
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(payload)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": payload})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", ()):
            if name == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                await self._refuse(send)
                return

        received = 0
        started = False
        tripped = False

        async def bounded_receive():
            nonlocal received, tripped
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    tripped = True
                    raise _BodyTooLarge
            return message

        async def tracking_send(message) -> None:
            # FastAPI catches ANY exception raised while it reads a body and
            # answers 400 "There was an error parsing the body" in its own
            # `detail` shape. The cut-off already happened -- nothing past the
            # cap was buffered -- but the answer should say what happened, in
            # the shape every other failure here uses. So once the cap has
            # tripped, the app's own response is replaced, not forwarded.
            nonlocal started
            if tripped:
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await self._refuse(send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracking_send)
        except _BodyTooLarge:
            # The body is read before any response starts, so this is the
            # normal case; if something did start answering, the connection is
            # simply dropped rather than given two responses.
            if not started:
                await self._refuse(send)


def install(app: FastAPI, cors_origins: list[str]) -> None:
    """Put the perimeter on `app`. Middleware added later wraps what was added
    earlier, so the order below reads inside-out."""
    app.middleware("http")(_security_headers)
    app.add_middleware(BoundBody)
    # The browser refuses a cross-origin request before the route is ever
    # reached, so a missing CORS layer presents as "the endpoint does not
    # exist" in a console and gets diagnosed as a backend bug. Explicit
    # origins, never "*": every authenticated call carries a bearer token, and
    # a wildcard origin with credentials is a combination browsers reject.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        # So a 429 can actually be obeyed: without this the browser hides the
        # header from the page and the client cannot tell the user how long.
        expose_headers=["Retry-After"],
        max_age=600,
    )
    app.add_exception_handler(RequestValidationError, _flat_validation_errors)
    app.add_exception_handler(HTTPException, _flat_errors)
