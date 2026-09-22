"""Grant, revoke and list platform admins. The only way to create one.

    python -m server.admin_cli grant  ada@example.com
    python -m server.admin_cli revoke ada@example.com
    python -m server.admin_cli list

Run it where the server runs (Render: the service's Shell tab), against the
same READBACK_DATABASE_URL. There is deliberately no HTTP path to this: sign-up
is open and email is never verified, so any web route that could make an admin
would be one an attacker could reach. The account must already exist -- sign
up through the app first, then grant.

Every grant and revoke is written to the audit log with actor "cli".
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from server import audit
from server.db import create_all, get_sessionmaker
from server.models import PlatformAdmin, User


def _usage() -> int:
    print(__doc__.strip().split("\n\n")[1])
    return 2


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("grant", "revoke", "list"):
        return _usage()
    create_all()
    with get_sessionmaker()() as db:
        if argv[0] == "list":
            rows = db.execute(select(User.email, PlatformAdmin.granted_at, PlatformAdmin.granted_by)
                              .join(PlatformAdmin, PlatformAdmin.user_id == User.id)
                              .order_by(User.email)).all()
            if not rows:
                print("no platform admins")
            for email, at, by in rows:
                print(f"{email}\tgranted {at:%Y-%m-%d %H:%M} UTC by {by}")
            return 0

        if len(argv) != 2:
            return _usage()
        email = argv[1].strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"no account for {email}: sign up in the app first", file=sys.stderr)
            return 1

        existing = db.get(PlatformAdmin, user.id)
        if argv[0] == "grant":
            if existing is not None:
                print(f"{email} is already an admin")
                return 0
            db.add(PlatformAdmin(user_id=user.id, granted_by="cli"))
            audit.record(db, audit.ADMIN_GRANTED, organisation_id=user.organisation_id,
                         actor="cli", detail={"user_id": str(user.id)})
            db.commit()
            print(f"granted: {email}")
            return 0

        if existing is None:
            print(f"{email} is not an admin")
            return 0
        db.delete(existing)
        audit.record(db, audit.ADMIN_REVOKED, organisation_id=user.organisation_id,
                     actor="cli", detail={"user_id": str(user.id)})
        db.commit()
        print(f"revoked: {email}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
