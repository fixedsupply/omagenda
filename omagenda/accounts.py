"""Account management.

`omagenda account add|list|remove`: writes ~/.config/omagenda/config.toml
entries, generates a pimsync config for icloud/caldav accounts, and stores
credentials via the keyring (secret-tool), falling back to a mode-0600 file
when no keyring is available. See ARCHITECTURE.md §5 and §11.

Not yet implemented: Phase 1b (see AGENTS.md).
"""
