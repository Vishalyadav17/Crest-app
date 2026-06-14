"""NotebookLM connector — pull source-grounded fundamentals (revenue/PAT/guidance) from
per-company Google NotebookLM notebooks into the platform.

Bridges to the local `notebooklm` Claude skill, which drives a persistent-auth browser session
and answers strictly from the notebook's uploaded documents (no hallucination). We shell out to
its CLI and parse a structured JSON answer.

SETUP REQUIRED before this returns data:
  1. Create a NotebookLM notebook per company (the user is doing this).
  2. Map symbol → notebook URL in data/notebook_map.json  ({"GRSE": "https://notebooklm.google.com/notebook/..."}).
  3. Ensure the skill is authed:  python ~/.claude/skills/notebooklm/scripts/run.py auth_manager.py status

Until a symbol is mapped, fetch_fundamentals() returns None and callers fall back gracefully.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_SKILL_DIR = Path(os.path.expanduser("~/.claude/skills/notebooklm/scripts"))
_RUN = _SKILL_DIR / "run.py"
_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "notebook_map.json"

_QUESTION = (
    "From this company's documents, extract the most recent management guidance. "
    "Reply ONLY with JSON, all figures in INR crore, null if not stated: "
    '{"fy_revenue_guidance_cr":<num|null>,"q_revenue_guidance_cr":<num|null>,'
    '"pat_guidance_cr":<num|null>,"as_of":"<fiscal period or date>","note":"<one line>"}'
)


def load_map() -> dict[str, str]:
    try:
        return json.loads(_MAP_PATH.read_text()) if _MAP_PATH.exists() else {}
    except Exception:
        log.warning("notebook_map.json unreadable")
        return {}


def get_notebook_url(sym: str) -> str | None:
    return load_map().get(sym.upper())


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def fetch_fundamentals(sym: str, *, timeout: int = 180) -> dict | None:
    """Query the company's notebook for guidance figures. Returns parsed dict or None."""
    url = get_notebook_url(sym)
    if not url or not _RUN.exists():
        return None
    try:
        proc = subprocess.run(
            ["python", str(_RUN), "ask_question.py", "--question", _QUESTION, "--notebook-url", url],
            cwd=str(_SKILL_DIR), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.warning("notebooklm: timeout querying %s", sym)
        return None
    except Exception as e:
        log.warning("notebooklm: failed querying %s: %s", sym, e)
        return None
    if proc.returncode != 0:
        log.warning("notebooklm: skill exited %d for %s: %s", proc.returncode, sym, proc.stderr[:200])
        return None
    return _extract_json(proc.stdout)


def sync_guidance(db, sym: str) -> bool:
    """Fetch from NotebookLM and upsert EarningsGuidance. Returns True if updated."""
    from models import EarningsGuidance

    data = fetch_fundamentals(sym)
    if not data:
        return False

    row = db.query(EarningsGuidance).filter(EarningsGuidance.sym == sym.upper()).first()
    if row is None:
        row = EarningsGuidance(sym=sym.upper())
        db.add(row)
    if data.get("fy_revenue_guidance_cr") is not None:
        row.fy_revenue_guidance_cr = data["fy_revenue_guidance_cr"]
    if data.get("q_revenue_guidance_cr") is not None:
        row.q_revenue_guidance_cr = data["q_revenue_guidance_cr"]
    pat = data.get("pat_guidance_cr")
    note = data.get("note") or ""
    row.guidance_note = (f"PAT guidance ₹{pat} cr. " if pat is not None else "") + note + " [via NotebookLM]"
    row.guidance_as_of = data.get("as_of")
    db.commit()
    log.info("notebooklm: synced guidance for %s", sym)
    return True
