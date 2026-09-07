"""Deterministic natural-language event parser.

Single pass over tokens, no network, no guessing: ambiguous input returns
warnings instead of a silent guess. The grammar this module implements is
documented in nl_grammar.md and specified by the corpus in
tests/test_parse.py. See ARCHITECTURE.md §6.

Not yet implemented: Phase 1 (see AGENTS.md).
"""
