"""Vdir discovery and atomic write tests. See ARCHITECTURE.md §7 and §9.

Not yet implemented: Phase 1 (see AGENTS.md). Point OMAGENDA_VDIR at
tests/fixtures/vdir/ for development.
"""
import unittest


class VdirTest(unittest.TestCase):
    @unittest.expectedFailure
    def test_discovers_fixture_calendars(self):
        from omagenda.vdir import discover_calendars

        cals = discover_calendars("tests/fixtures/vdir")
        ids = sorted(c["id"] for c in cals)
        self.assertEqual(ids, ["family", "personal", "work"])


if __name__ == "__main__":
    unittest.main()
