"""
Thin shim — re-exports create_scheduler and get_scheduler from jobs package.
main.py imports unchanged: `from scheduler import create_scheduler, get_scheduler`.
"""
from jobs import create_scheduler, get_scheduler

__all__ = ["create_scheduler", "get_scheduler"]
