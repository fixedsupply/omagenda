"""Exercise day delegate replacement without loading the installed shell."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


class PanelNavigationTest(unittest.TestCase):
    def test_day_tap_survives_delegate_replacement(self):
        runner = Path("/usr/lib/qt6/bin/qmltestrunner")
        if not runner.exists():
            self.skipTest("Qt QML test runtime is unavailable")
        panel = (Path(__file__).resolve().parents[1] / "qml/Panel.qml").read_text()
        function = re.search(r"  function selectDay\(key\) \{.*?\n  }", panel, re.S).group()
        handler = re.search(r"onTapped: root.selectDay\(dayCell.modelData.key\)", panel).group()
        template = '''import QtQuick
import QtTest
Item {
    id: root
    width: 200; height: 100
    property string selectedKey: "first"
    property int cursorIndex: 3
    property bool expanded: true
    property string cancelled: ""
    function cancelDelete(action) { cancelled = action }
    FUNCTION
    Repeater {
        model: [{ key: root.selectedKey === "first" ? "second" : "first" }]
        delegate: Rectangle {
            id: dayCell
            required property var modelData
            width: 100; height: 100
            TapHandler { HANDLER }
        }
    }
    TestCase {
        name: "DaySelection"
        when: windowShown
        function test_tap() {
            mouseClick(root, 50, 50)
            compare(root.selectedKey, "second")
            compare(root.cursorIndex, 0)
            compare(root.expanded, false)
            compare(root.cancelled, "day")
        }
    }
}
'''
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="basic",
                   QT_QUICK_BACKEND="software")
        with tempfile.TemporaryDirectory() as tmp:
            qml = Path(tmp) / "tst_navigation.qml"
            def run(tap):
                qml.write_text(template.replace("FUNCTION", function).replace("HANDLER", tap))
                return subprocess.run([str(runner), "-input", tmp], env=env,
                                      capture_output=True, text=True, timeout=30)
            old = run('onTapped: { root.selectedKey = dayCell.modelData.key; root.cursorIndex = 0; root.expanded = false }')
            self.assertNotEqual(old.returncode, 0, old.stdout + old.stderr)
            self.assertIn("root is not defined", old.stdout + old.stderr)
            fixed = run(handler)
            self.assertEqual(fixed.returncode, 0, fixed.stdout + fixed.stderr)
            self.assertNotIn("ReferenceError", fixed.stdout + fixed.stderr)
