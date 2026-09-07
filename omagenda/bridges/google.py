"""Google Calendar bridge.

OAuth 2.0 loopback + PKCE against the project's desktop-app client (see
docs/google-cloud-setup.md), incremental sync via syncToken, conditional
writes via ETag, JSON<->VEVENT mapping per ARCHITECTURE.md §11.

Not yet implemented: Phase 1b (see AGENTS.md).
"""
