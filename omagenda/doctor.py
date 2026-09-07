"""Environment diagnostics.

Checks: required Python packages, vdir presence, configured sync tool
(pimsync/vdirsyncer) on PATH, keyring availability, the plugin's enabled
state in shell.json, and (once accounts exist) each account's OAuth token
health. Backs `omagenda doctor`. See ARCHITECTURE.md §9.

Not yet implemented: Phase 1 (see AGENTS.md).
"""
