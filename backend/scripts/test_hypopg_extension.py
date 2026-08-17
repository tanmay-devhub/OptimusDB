"""Phase 10.1 smoke test - HypoPG extension is installed and callable.

Idempotently CREATE EXTENSION IF NOT EXISTS so an existing pgdata volume
picks up the extension without a fresh init. Then exercises the two
HypoPG functions OptimusDB depends on:

    * hypopg_create_index(sql)  -> registers a hypothetical index
    * hypopg_reset()            -> clears every hypothetical index

Exit 0 on success, 1 on any check failure.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


def _connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "optimus"),
        password=os.getenv("PG_PASSWORD", "optimus"),
        dbname=os.getenv("PG_DB", "tpch"),
    )


def _hr(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    conn = _connect()
    conn.autocommit = True
    failures: list[str] = []
    try:
        _hr("Phase 10.1 - HypoPG extension")

        # 1. Extension installable
        with conn.cursor() as cur:
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS hypopg")
                print("  [OK]   CREATE EXTENSION IF NOT EXISTS hypopg")
            except Exception as exc:
                failures.append(f"CREATE EXTENSION failed: {exc}")
                print(f"  [FAIL] CREATE EXTENSION: {exc}")
                return 1

        # 2. Extension registered in pg_extension
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'hypopg'"
            )
            row = cur.fetchone()
            if row is None:
                failures.append("hypopg not present in pg_extension")
                print("  [FAIL] hypopg not present in pg_extension")
            else:
                print(f"  [OK]   pg_extension row present (version={row[0]})")

        # 3. hypopg_create_index returns a hypothetical index oid
        with conn.cursor() as cur:
            cur.execute("SELECT hypopg_reset()")  # clean slate
            cur.execute(
                "SELECT indexrelid FROM hypopg_create_index("
                "  'CREATE INDEX ON orders (o_custkey)'"
                ")"
            )
            oid = cur.fetchone()
            if oid is None or oid[0] is None:
                failures.append("hypopg_create_index returned no oid")
                print("  [FAIL] hypopg_create_index returned no oid")
            else:
                print(f"  [OK]   hypopg_create_index returned oid={oid[0]}")

        # 4. hypopg_reset clears the hypothetical index
        with conn.cursor() as cur:
            cur.execute("SELECT hypopg_reset()")
            cur.execute("SELECT COUNT(*) FROM hypopg()")
            n = cur.fetchone()[0]
            if n != 0:
                failures.append(f"hypopg_reset left {n} index(es)")
                print(f"  [FAIL] hypopg_reset left {n} index(es)")
            else:
                print("  [OK]   hypopg_reset() cleared all hypothetical indexes")

        _hr("Phase 10.1 report")
        if failures:
            print(f"  FAILED ({len(failures)} check(s)):")
            for f in failures:
                print(f"    - {f}")
            return 1
        print("  PASSED - HypoPG installed and callable.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
