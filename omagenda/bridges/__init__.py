"""Bridge interface for cloud calendar accounts.

Every bridge (Google, Microsoft) implements the same protocol: authorize,
list_calendars, pull, push_create, push_update, push_delete. See
ARCHITECTURE.md §11 for the exact interface and the pull/push algorithm.

Not yet implemented: Phase 1b (Google), Phase 5 (Microsoft) — see AGENTS.md.
"""
