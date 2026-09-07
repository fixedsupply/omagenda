"""Agenda indexing: expand vdir events into agenda.json.

Reads every calendar's .ics files, expands recurrence (including EXDATE and
RECURRENCE-ID exceptions) into concrete occurrences over a date range,
resolves conference links, and writes ~/.local/state/omagenda/agenda.json
atomically. Backs `omagenda index`, `agenda`, and `next`. See
ARCHITECTURE.md §3 and §4.

Not yet implemented: Phase 1 (see AGENTS.md).
"""
