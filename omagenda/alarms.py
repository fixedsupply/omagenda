"""Alarm scheduling for `omagenda watch`.

Fires omarchy-notification-send at each VALARM (or a per-calendar default
lead), with --exec Join when a conference URL exists, deduplicated across
restarts through a small state file. See PLAN.md §6.5 and ARCHITECTURE.md §3.

Not yet implemented: Phase 1 (see AGENTS.md).
"""
