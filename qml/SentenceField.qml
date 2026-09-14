import QtQuick

// Native editing remains responsible for selection, clipboard and input methods.
TextInput {
  id: field
  clip: true
  selectByMouse: true
  activeFocusOnTab: true
  signal saveRequested(bool keepOpen)
  signal cancelRequested()
  signal calendarRequested()

  Keys.onPressed: function(event) {
    if (inputMethodComposing) return
    if (event.key === Qt.Key_Escape) {
      cancelRequested()
      event.accepted = true
    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      saveRequested((event.modifiers & Qt.ShiftModifier) !== 0)
      event.accepted = true
    } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
      calendarRequested()
      event.accepted = true
    }
  }
}
