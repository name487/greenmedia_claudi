"""Admin commands for a real (non-demo) installation.

    python -m app.manage create-admin --email you@agency.com --name "Your Name" [--agency "Green Media Technology"]
    python -m app.manage import-clients clients.csv [--agency "Green Media Technology"]
    python -m app.manage clients-template > clients.csv
    python -m app.manage send-test-sms 98XXXXXXXX      # send one sign-in SMS and print the provider's reply

Creates the database tables if needed, the agency (tenant) with its built-in roles if it doesn't exist,
and an Admin user. The password is prompted for (never pass it on the command line)."""

import argparse
import getpass
import sys

from sqlalchemy import func, select

from . import importer, sms
from . import phone as phones
from .config import settings
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


def send_test_sms(mobile: str, code: str = "") -> str:
    """Skips the account check, so it shows exactly what the SMS provider says about this number."""
    phone = phones.normalize(mobile)
    code = code or "123456"[: settings.otp_length].ljust(settings.otp_length, "0")
    lines = [sms.describe(), f"To {phone}, code {code}"]
    try:
        lines.append("Provider replied: " + sms.send_otp(phone, code))
    except sms.SmsError as e:
        lines.append(f"FAILED: {e}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.manage")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin", help="create the first Admin user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--agency", default="Green Media Technology")
    imp = sub.add_parser("import-clients", help="bulk-create clients from a CSV file")
    imp.add_argument("csv_file")
    imp.add_argument("--agency", default="Green Media Technology")
    sub.add_parser("clients-template", help="print an example clients CSV")
    t = sub.add_parser("send-test-sms", help="send one sign-in SMS (code 123456) and print the provider's reply")
    t.add_argument("mobile")
    t.add_argument("--code", default="")
    args = p.parse_args(argv)

    if args.cmd == "send-test-sms":
        print(send_test_sms(args.mobile, args.code))
        return
    if args.cmd == "clients-template":
        print(importer.TEMPLATE, end="")
        return
    if args.cmd == "import-clients":
        init_db(seed_if_empty=False)
        with open(args.csv_file, encoding="utf-8-sig") as fh:
            text = fh.read()
        with SessionLocal() as db:
            tenant = db.scalar(select(Tenant).where(Tenant.name == args.agency))
            if tenant is None:
                sys.exit(f"No agency named {args.agency!r}. Run create-admin first.")
            out = importer.import_clients(db, tenant.id, None, text)
        if out["errors"]:
            print("Nothing imported. Fix these rows and run again:", *out["errors"], sep="\n  ")
            sys.exit(1)
        print(f"Imported {out['created']} clients." + (f" Skipped (already exist): {', '.join(out['skipped'])}" if out["skipped"] else ""))
        return

    if args.cmd == "create-admin":
        pw = getpass.getpass("Password (min 8 chars): ")
        if len(pw) < 8 or pw != getpass.getpass("Repeat password: "):
            sys.exit("Passwords must match and be at least 8 characters.")
        u = create_admin(args.email.strip(), args.name.strip(), args.agency.strip(), pw)
        print(f"Created admin {u.email}. Sign in at the web app.")


if __name__ == "__main__":
    main()
