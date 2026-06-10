#!/usr/bin/env python3
"""Generate pgAdmin server config from .env DATABASE_URL, then start pgAdmin on :5050."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docker" / "pgadmin"


def load_database_url() -> str:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found in .env or environment.")
    return url


def main() -> int:
    url = load_database_url()
    p = urlparse(url)
    host = p.hostname or ""
    port = p.port or 5432
    db = (p.path or "/defaultdb").lstrip("/").split("?")[0] or "defaultdb"
    user = unquote(p.username or "")
    password = unquote(p.password or "")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    template = (ROOT / "docker" / "pgadmin" / "servers.json.template").read_text()
    servers_body = (
        template.replace("HOST_PLACEHOLDER", host)
        .replace("PORT_PLACEHOLDER", str(port))
        .replace("DB_PLACEHOLDER", db)
        .replace("USER_PLACEHOLDER", user)
    )
    servers = json.loads(servers_body)
    (OUT_DIR / "servers.json").write_text(json.dumps(servers, indent=2))

    # pgpass: hostname:port:database:username:password
    pgpass_line = f"{host}:{port}:{db}:{user}:{password}\n"
    pgpass_path = OUT_DIR / "pgpass"
    pgpass_path.write_text(pgpass_line)
    pgpass_path.chmod(0o600)

    print("Wrote docker/pgadmin/servers.json and pgpass")
    print(f"  Host: {host}:{port}  DB: {db}  User: {user}")
    print("\nStarting pgAdmin (profile: tools)...")
    print("  URL: http://localhost:5050/")
    print("  Login email:    admin@expense.com")
    print("  Login password: admin\n")

    cmd = [
        "docker",
        "compose",
        "--profile",
        "tools",
        "up",
        "-d",
        "pgadmin",
    ]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
