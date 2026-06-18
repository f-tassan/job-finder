"""Bring the database to the latest Alembic revision before the API starts.

The provided docker-compose mounts `db/schema.sql` into Postgres'
`docker-entrypoint-initdb.d`, so on a *fresh* volume Postgres creates the full
schema on first boot. Alembic is still the source of truth (the first migration
reproduces that schema), so we reconcile the two cases:

* DB already stamped (has `alembic_version`)  -> `alembic upgrade head`
* schema present from initdb but unstamped     -> `alembic stamp head`
* empty DB (no initdb mount)                    -> `alembic upgrade head`

This keeps the provided compose untouched while making Alembic authoritative.
"""
from __future__ import annotations

import subprocess
import sys
import time

import psycopg

from app.config import settings


def _connect(retries: int = 30, delay: float = 1.0) -> psycopg.Connection:
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )
    last: Exception | None = None
    for _ in range(retries):
        try:
            return psycopg.connect(dsn)
        except Exception as exc:  # noqa: BLE001 - retry on any connection error
            last = exc
            time.sleep(delay)
    raise SystemExit(f"could not connect to Postgres: {last}")


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))
        return bool(cur.fetchone()[0])


def main() -> None:
    with _connect() as conn:
        already_stamped = _table_exists(conn, "alembic_version")
        schema_present = _table_exists(conn, "app_user")

    if schema_present and not already_stamped:
        action = ["alembic", "stamp", "head"]
        print("prestart: schema present from initdb -> stamping Alembic head")
    else:
        action = ["alembic", "upgrade", "head"]
        print("prestart: running Alembic upgrade head")

    sys.exit(subprocess.call(action))


if __name__ == "__main__":
    main()
