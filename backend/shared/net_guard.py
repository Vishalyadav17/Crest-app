"""Connectivity guard — nightly scan/track must no-op when offline."""
from __future__ import annotations
import logging
import socket

log = logging.getLogger(__name__)


def has_internet(timeout: float = 4.0) -> bool:
    """True if we can reach the open internet. Tries a couple of DNS roots."""
    for host, port in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    log.warning("net_guard: no internet connectivity — skipping")
    return False
