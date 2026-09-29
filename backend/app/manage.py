"""Admin commands for a real (non-demo) installation.

    python -m app.manage create-admin --email you@agency.com --name "Your Name" [--agency "Green Media Technology"]

Creates the database tables if needed, the agency (tenant) with its built-in roles if it doesn't exist,
and an Admin user. The password is prompted for (never pass it on the command line)."""

import argparse
import getpass
import sys

from sqlalchemy import func, select

from .db import SessionLocal
from .models import Tenant, User
from .security import ensure_default_roles, hash_password
from .seed import init_db


def create_admin(email: str, name: str, agency: str, password: str) -> User:
    init_db(seed_if_empty=False)
    with SessionLocal() as db:
        if db.scalar(select(User).where(func.lower(User.email) == email.lower())):
            raise SystemExit(f"A user with email {email} already exists.")
        tenant = db.scalar(select(Tenant).where(Tenant.name == agency))
        if tenant is None:
            tenant = Tenant(name=agency)
            db.add(tenant)
            db.flush()
        ensure_default_roles(db, tenant.id)
        user = User(tenant_id=tenant.id, name=name, email=email.lower(), password_hash=hash_password(password), role="admin")
        db.add(user)
        db.commit()
        return user


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.manage")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin", help="create the first Admin user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--agency", default="Green Media Technology")
    args = p.parse_args(argv)

    if args.cmd == "create-admin":
        pw = getpass.getpass("Password (min 8 chars): ")
        if len(pw) < 8 or pw != getpass.getpass("Repeat password: "):
            sys.exit("Passwords must match and be at least 8 characters.")
        u = create_admin(args.email.strip(), args.name.strip(), args.agency.strip(), pw)
        print(f"Created admin {u.email}. Sign in at the web app.")


if __name__ == "__main__":
    main()
