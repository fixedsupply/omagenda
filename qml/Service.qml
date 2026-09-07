import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

// Headless service: starts `omagenda watch`, owns the agenda.json FileView,
// and exposes the "omagenda" IPC target (toggle, quickAdd, sync, next).
// See ARCHITECTURE.md §3 and §8.
//
// Not yet implemented: Phase 2 (see AGENTS.md).
QtObject {
  id: root
}
