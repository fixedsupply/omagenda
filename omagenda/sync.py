"""Sync orchestration.

Runs the configured bridges (Google, Microsoft), delegates CalDAV accounts
to pimsync or vdirsyncer, fetches read-only ICS subscriptions, and merges
an optional OmaCal read-only view, then reindexes. Backs `omagenda sync`.
See ARCHITECTURE.md §7 and §11.

Not yet implemented: Phase 1 (delegation) and Phase 1b (bridges) — see
AGENTS.md.
"""
