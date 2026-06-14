#!/usr/bin/env bash
# Run all test files serially.
# Full `pytest -q` hangs when live yfinance/network tests contend with a running :8000 app.
set -e

PYTHON="${PYTHON:-.venv/bin/python}"
PASS=0
FAIL=0
FAILED_FILES=""

run_file() {
    local f="$1"
    echo "── $f"
    if "$PYTHON" -m pytest "$f" -q --tb=short 2>&1; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        FAILED_FILES="$FAILED_FILES $f"
    fi
}

# Core unit tests (no app startup needed)
run_file tests/test_sepa.py
run_file tests/test_tradeability.py
run_file tests/test_breakout.py
run_file tests/test_position_sizing.py
run_file tests/test_order_flow.py
run_file tests/test_scheduler_helpers.py
run_file tests/test_llm_router.py
run_file tests/test_custom_index.py

# Integration tests (require Postgres + FastAPI app bootstrap)
run_file tests/test_phase3.py
run_file tests/test_phase6.py
run_file tests/test_research.py
run_file tests/test_portfolio_global.py
run_file tests/test_settings_routes.py

echo ""
echo "── Summary: $PASS files passed, $FAIL failed"
if [ $FAIL -ne 0 ]; then
    echo "Failed:$FAILED_FILES"
    exit 1
fi
