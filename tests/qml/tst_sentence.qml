import QtQuick
import QtTest
import "../../qml"

TestCase {
  name: "SentenceEditing"
  when: windowShown
  width: 500
  height: 100
  SentenceField { id: field; width: 480; height: 40 }
  SignalSpy { id: saves; target: field; signalName: "saveRequested" }
  SignalSpy { id: calendars; target: field; signalName: "calendarRequested" }
  function init() { field.text = "Lunch Friday"; field.forceActiveFocus(); saves.clear(); calendars.clear() }
  function test_insert_at_cursor() {
    field.cursorPosition = 5
    keyClick(Qt.Key_Space)
    keyClick(Qt.Key_A)
    compare(field.text, "Lunch a Friday")
  }
  function test_selection_replace() {
    field.select(6, 12)
    keyClick(Qt.Key_M)
    compare(field.text, "Lunch m")
  }
  function test_shortcuts() {
    keyClick(Qt.Key_Return, Qt.ShiftModifier)
    compare(saves.count, 1)
    compare(saves.signalArguments[0][0], true)
    keyClick(Qt.Key_Tab)
    compare(calendars.count, 1)
  }
  function test_undo_and_clipboard() {
    field.selectAll()
    field.copy()
    field.cut()
    compare(field.text, "")
    field.paste()
    compare(field.text, "Lunch Friday")
    keyClick(Qt.Key_Z, Qt.ControlModifier)
    compare(field.text, "")
  }
}
