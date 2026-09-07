import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Natural-language event entry overlay. Follows the centered-card, scrim,
// and key-catcher pattern in plugins/reminders/ReminderFlow.qml.
//
// Not yet implemented: Phase 3 (see AGENTS.md).
Item {
  id: root
  property var shell: null
  property var manifest: null
  function open(payloadJson) {}
  function close() {}
  function toggle() {}
}
