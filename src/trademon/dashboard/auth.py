"""Who is making a change — a seam, not a security system.

Right now the dashboard runs on a private network with no login, which is a deliberate
choice for a single-user home setup. This module exists so that adding accounts or SSO
later is one implementation, not an edit to every place that writes something: the
config screen already asks `current_user()` before each write and stamps the answer into
the change journal, so history from before and after the change stays comparable.

To add real auth later, implement `current_user()` (returning None for anonymous) and
`can_write()`; the call sites do not move.
"""

from __future__ import annotations

LOCAL_USER = "local"


def current_user() -> str:
    """Identity to record against a configuration change."""
    return LOCAL_USER


def can_write() -> bool:
    """Whether the current viewer may change configuration."""
    return True
