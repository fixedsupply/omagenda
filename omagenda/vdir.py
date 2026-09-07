"""Vdir discovery and event I/O.

Discovers calendars under a vdir root (~/.local/share/calendars by default,
or $OMAGENDA_VDIR for development and tests), reads each calendar's
displayname/color files, maps colors to theme-native names, and writes new
event files atomically. See ARCHITECTURE.md §1 and §7.

Not yet implemented: Phase 1 (see AGENTS.md).
"""
