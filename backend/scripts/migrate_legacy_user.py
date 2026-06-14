"""
One-time migration: move all data from user_id=1 (legacy seed) → user_id=2 (real Google account),
then delete user_id=1.

Run from growpilot/backend/:
    .venv/bin/python scripts/migrate_legacy_user.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import engine

FROM_ID = 1
TO_ID   = 2

# Tables where user_id is a plain FK column (safe to bulk UPDATE)
SIMPLE_TABLES = [
    "equity_holdings",
    "portfolio_meta",
    "global_holdings",
    "crypto_holdings",
    "mf_holdings",
    "mf_watchpoints",
    "investment_thesis",
    "swing_trades",
    "watchlists",
    "scan_runs",
    "scan_outcomes",
    "import_jobs",
    "price_alerts",
    "notifications",
    "user_dashboard_modules",
]

def run():
    with engine.begin() as conn:
        # user_preferences has a unique(user_id, key) constraint.
        # Delete TO_ID rows whose key already exists in FROM_ID's rows,
        # then bulk-update the rest.
        print("Handling user_preferences conflict...")
        conn.execute(text("""
            DELETE FROM user_preferences
            WHERE user_id = :to
              AND key IN (
                SELECT key FROM user_preferences WHERE user_id = :from
              )
        """), {"from": FROM_ID, "to": TO_ID})
        conn.execute(text(
            "UPDATE user_preferences SET user_id = :to WHERE user_id = :from"
        ), {"from": FROM_ID, "to": TO_ID})
        print("  user_preferences: done")

        for table in SIMPLE_TABLES:
            result = conn.execute(text(
                f"UPDATE {table} SET user_id = :to WHERE user_id = :from"
            ), {"from": FROM_ID, "to": TO_ID})
            if result.rowcount:
                print(f"  {table}: {result.rowcount} rows moved")

        conn.execute(text("DELETE FROM users WHERE id = :from"), {"from": FROM_ID})
        print(f"  users: id={FROM_ID} deleted")

    print("\nDone. All data is now under user_id=2.")

if __name__ == "__main__":
    run()
