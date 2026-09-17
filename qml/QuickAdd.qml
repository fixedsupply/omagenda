// Quick Add: type a sentence, get an event.
//
// A centred card over a scrim, following plugins/reminders/ReminderFlow.qml
// with a native text input for cursor movement, selection, paste and IME.
//
// The parser runs out of process (`omagenda parse --json`), debounced, and
// only one at a time: a keystroke that lands while a parse is in flight
// queues the newest text and runs it when that one returns, so a fast
// typist never stacks up interpreters. See ARCHITECTURE.md §6 and §8.
//
// Reached through the plugin's own IPC target rather than the shell's
// generic summon: this plugin owns a bar widget, and the shell routes
// summon for such a plugin to the widget's panel (shell.qml's
// isBarWidgetPanelPlugin), so a second surface needs its own door.

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Model.js" as Model

Item {
  id: root

  property var service: null
  property string binPath: ""
  property string prefillDate: ""
  property string editFile: ""
  readonly property bool editing: editFile !== ""
  property bool savedUpdate: false

  property bool opened: false
  property string text: ""
  // "" means "let the CLI decide" -- a /tag in the sentence, then the
  // configured default, then the first writable calendar. Tab overrides
  // that for this one event without changing anyone's default.
  property string targetCalendar: ""
  property var parsed: null
  property string parseError: ""
  property bool busy: false
  property string pendingText: ""
  property string parsingText: ""
  property bool keepOpenAfterSave: false
  property string savedTitle: ""
  property string saveError: ""
  property bool saveWaitElapsed: false

  readonly property color foreground: Color.menu.text
  readonly property color accent: Color.accent
  readonly property string fontFamily: Style.font.menuFamily
  readonly property string timeFormat: Model.resolveTimeFormat(
    "system", Qt.locale().timeFormat(Locale.ShortFormat).indexOf("AP") === -1)

  readonly property string preview: Model.previewLine(parsed, timeFormat)
  readonly property string saveProgress: Model.saveProgressText(addProc.running, saveWaitElapsed)
  readonly property var warnings: parsed && parsed.warnings ? parsed.warnings : []
  readonly property var agenda: service ? service.agenda : ({ calendars: [], events: [] })

  // What the event will land in, said plainly: a /tag in the sentence wins,
  // then a Tab choice, then the configured default the CLI would apply.
  readonly property string effectiveCalendar: {
    if (editing) return targetCalendar
    if (parsed && parsed.calendar) return parsed.calendar
    if (targetCalendar !== "") return targetCalendar
    return service && service.defaultCalendar ? service.defaultCalendar : ""
  }

  signal added(string title)
  signal updated(string title)

  property string cycleNote: ""

  function cycleCalendar() {
    if (root.editing) return
    var reason = Model.cycleUnavailableReason(root.agenda, root.effectiveCalendar)
    if (reason !== "") {
      // Say why rather than appearing broken.
      root.cycleNote = reason
      cycleNoteTimer.restart()
      return
    }
    root.cycleNote = ""
    var next = Model.nextCalendarId(root.agenda, root.effectiveCalendar)
    if (next !== "") root.targetCalendar = next
  }

  function open(dateKey) {
    if (addProc.running) return
    root.editFile = ""
    root.saveError = ""
    root.keepOpenAfterSave = false
    root.prefillDate = dateKey || ""
    root.targetCalendar = ""
    root.cycleNote = ""
    root.text = ""
    root.parsed = null
    root.parseError = ""
    root.opened = true
    Qt.callLater(function() { field.forceActiveFocus() })
  }

  function openEdit(file, sentence, calendar) {
    if (addProc.running) return
    open("")
    root.editFile = file
    root.targetCalendar = calendar
    root.setText(sentence)
    Qt.callLater(function() {
      field.forceActiveFocus()
      field.cursorPosition = field.text.length
    })
  }

  function close() {
    root.opened = false
    root.text = ""
    root.parsed = null
  }

  function setText(next) {
    root.text = next
    if (next.trim() === "") {
      root.parsed = null
      return
    }
    parseDebounce.restart()
  }

  function runParse() {
    if (root.busy) {
      // Keep only the newest; an interpreter per keystroke helps nobody.
      root.pendingText = root.text
      return
    }
    root.busy = true
    root.parsingText = root.text
    parseProc.command = [root.binPath, "parse", root.sentence(), "--json"]
    parseProc.running = true
  }

  // A date picked in the panel is context the sentence shouldn't have to
  // repeat, so it's appended only when the user hasn't named a day.
  function sentence() {
    var typed = root.text.trim()
    if (root.editing || !root.prefillDate) return typed
    if (root.parsed && root.parsed.spans) {
      for (var i = 0; i < root.parsed.spans.length; i++) {
        if (root.parsed.spans[i].kind === "date") return typed
      }
    }
    return typed + " " + root.prefillDate
  }

  function submit(keepOpen) {
    if (addProc.running || (root.editing && keepOpen)) return
    if (root.text.trim() === "") {
      root.close()
      return
    }
    var command = root.editing
      ? [root.binPath, "edit", root.editFile, root.sentence(), "--json"]
      : [root.binPath, "add", root.sentence(), "--json"]
    // Only when the user actually chose one: otherwise the CLI applies the
    // configured default, which is the behaviour they set up deliberately.
    if (!root.editing && root.targetCalendar !== "" && !(root.parsed && root.parsed.calendar))
      command = command.concat(["--calendar", root.targetCalendar])
    root.keepOpenAfterSave = keepOpen
    root.savedTitle = ""
    root.savedUpdate = false
    root.saveError = ""
    root.saveWaitElapsed = false
    addProc.command = command
    addProc.running = true
    saveWaitTimer.restart()
  }

  Timer {
    id: saveWaitTimer
    interval: 2000
    repeat: false
    onTriggered: if (addProc.running) root.saveWaitElapsed = true
  }

  Timer {
    id: cycleNoteTimer
    interval: 4000
    repeat: false
    onTriggered: root.cycleNote = ""
  }

  Timer {
    id: parseDebounce
    interval: 60
    repeat: false
    onTriggered: root.runParse()
  }

  Process {
    id: parseProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (!root.opened || root.text !== root.parsingText) return
        try {
          root.parsed = JSON.parse(text)
          root.parseError = ""
        } catch (e) {
          root.parseError = "couldn't read the parser's answer"
        }
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (root.opened && root.text === root.parsingText && text.trim() !== "") root.parseError = text.trim()
    }
    onExited: {
      root.busy = false
      if (root.opened && root.text.trim() !== "" && root.text !== root.parsingText) {
        root.pendingText = ""
        root.runParse()
      }
    }
  }

  Process {
    id: addProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          root.savedTitle = root.editing ? result.title : (result.event || {}).title || ""
          root.savedUpdate = result.updated === true
        } catch (e) {}
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.saveError = text.trim()
    }
    onExited: function(exitCode, exitStatus) {
      saveWaitTimer.stop()
      root.saveWaitElapsed = false
      if (exitCode !== 0) {
        root.parseError = root.saveError || "Could not save the event. Your text is still here."
        return
      }
      if (root.editing) {
        if (root.savedUpdate) root.updated(root.savedTitle)
      } else root.added(root.savedTitle)
      if (root.keepOpenAfterSave) {
        root.text = ""
        root.parsed = null
        field.forceActiveFocus()
      } else {
        root.close()
      }
      if (root.service) root.service.reload()
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omagenda-quick-add"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: Color.menu.scrim
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.close()
    }

    BorderSurface {
      id: card
      width: Math.min(Style.space(560), panel.width - Style.gapsOut * 2)
      height: content.implicitHeight + Style.spacing.panelPadding * 2
      radius: Style.cornerRadius
      anchors.centerIn: parent
      color: Color.menu.background
      borderSpec: Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(2)))
      padding: Style.spacing.panelPadding

      MouseArea { anchors.fill: parent; onClicked: {} }

      Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: card.contentLeftInset
        anchors.rightMargin: card.contentRightInset
        anchors.topMargin: card.contentTopInset
        spacing: Style.space(10)

        // ---- the sentence, with what was understood picked out ----------
        Item {
          width: parent.width
          height: Math.max(field.implicitHeight, Style.space(30))

          Text {
            id: placeholder
            visible: root.text === ""
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: root.editing ? "Edit this event…" : "Lunch with Sarah tomorrow at 1pm…"
            color: root.foreground
            opacity: 0.45
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
          }

          SentenceField {
            id: field
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            readOnly: addProc.running
            color: root.foreground
            selectionColor: root.accent
            selectedTextColor: Color.background
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            onTextEdited: root.setText(text)
            onSaveRequested: function(keepOpen) { root.submit(keepOpen) }
            // Closing leaves the child process running; it will still finish
            // its locked write and reload the agenda after the overlay hides.
            onCancelRequested: root.close()
            onCalendarRequested: root.cycleCalendar()
          }
        }

        PanelSeparator { foreground: root.foreground }

        // ---- what will actually be written ------------------------------
        Text {
          width: parent.width
          visible: root.saveProgress !== ""
          textFormat: Text.PlainText
          text: root.saveProgress
          color: root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          visible: root.preview !== ""
          text: root.preview
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
        }

        // Ambiguity is shown, never resolved silently (ARCHITECTURE.md §6).
        Repeater {
          model: root.warnings
          delegate: Text {
            required property string modelData
            width: content.width
            textFormat: Text.PlainText
            text: "! " + modelData
            color: Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }

        Text {
          width: parent.width
          visible: root.parseError !== ""
          textFormat: Text.PlainText
          text: root.parseError
          color: Color.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          visible: root.cycleNote !== ""
          text: root.cycleNote
          color: Qt.darker(root.foreground, 1.4)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          visible: root.effectiveCalendar !== ""
          text: Model.destinationText(root.agenda, root.effectiveCalendar)
                + (root.editing ? " (editing)" : root.parsed && root.parsed.calendar ? "  (from the sentence)" : "")
          color: root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: Model.quickAddHints(root.agenda, root.effectiveCalendar, root.editing)
          color: Qt.darker(root.foreground, 1.6)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.letterSpacing: 1.0
        }
      }
    }
  }
}
