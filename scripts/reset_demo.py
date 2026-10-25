"""Restore fictional seed state in the dedicated local PostgreSQL demo database."""

from run_step3 import make_store
from agent_commerce_security.runtime import load_fixture


def main() -> None:
    store = make_store()
    if not store.is_postgres:
        raise SystemExit("Use ACS_STORE=sqlite scripts/run_step3.py --reset for SQLite")
    seed = load_fixture("seed.json")
    with store.connect() as connection:
        database = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        if database != "agent_commerce_security_demo":
            raise SystemExit("Refusing to reset a database other than agent_commerce_security_demo")
    store.initialize(seed)
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("TRUNCATE security_events, outbox, audit_events, mock_ledger, purchases, quotes, "
                               "budgets, paid_reports, services, sellers, demo_users, tenants RESTART IDENTITY CASCADE")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    store.initialize(seed)
    print("Dedicated demo database restored to fictional seed state")


if __name__ == "__main__":
    main()
