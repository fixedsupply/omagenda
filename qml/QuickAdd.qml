// Quick Add: type a sentence, get an event.
//
// A centred card over a scrim, following plugins/reminders/ReminderFlow.qml
// -- including its most useful trick. The field is a plain Text driven by
// raw key events rather than a TextInput, which is what makes live
// highlighting tractable: there is no real caret to fight with the markup,
// so the sentence renders as StyledText with every recognised fragment in
// the accent colour and the caret is simply drawn on the end.
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

  readonly property color foreground: Color.menu.text
  readonly property color accent: Color.accent
  readonly property string fontFamily: Style.font.menuFamily
  readonly property string timeFormat: Model.resolveTimeFormat(
    "system", Qt.locale().timeFormat(Locale.ShortFormat).indexOf("AP") === -1)

  readonly property string highlighted: Model.highlightedHtml(
    root.text, parsed && parsed.spans ? parsed.spans : [], root.accent, root.foreground)
  readonly property string preview: Model.previewLine(parsed, timeFormat)
  readonly property var warnings: parsed && parsed.warnings ? parsed.warnings : []
  readonly property var agenda: service ? service.agenda : ({ calendars: [], events: [] })

  // What the event will land in, said plainly: a /tag in the sentence wins,
  // then a Tab choice, then the configured default the CLI would apply.
  readonly property string effectiveCalendar: {
    if (parsed && parsed.calendar) return parsed.calendar
    if (targetCalendar !== "") return targetCalendar
    return service && service.defaultCalendar ? service.defaultCalendar : ""
  }

  signal added(string title)

  function cycleCalendar() {
    var next = Model.nextCalendarId(root.agenda, root.effectiveCalendar)
    if (next !== "") root.targetCalendar = next
  }

  function open(dateKey) {
    root.prefillDate = dateKey || ""
    root.targetCalendar = ""
    root.text = ""
    root.parsed = null
    root.parseError = ""
    root.opened = true
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
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
    parseProc.command = [root.binPath, "parse", root.sentence(), "--json"]
    parseProc.running = true
  }

  // A date picked in the panel is context the sentence shouldn't have to
  // repeat, so it's appended only when the user hasn't named a day.
  function sentence() {
    var typed = root.text.trim()
    if (!root.prefillDate) return typed
    if (root.parsed && root.parsed.spans) {
      for (var i = 0; i < root.parsed.spans.length; i++) {
        if (root.parsed.spans[i].kind === "date") return typed
      }
    }
    return typed + " " + root.prefillDate
  }

  function submit(keepOpen) {
    if (root.text.trim() === "") {
      root.close()
      return
    }
    var command = [root.binPath, "add", root.sentence(), "--json"]
    // Only when the user actually chose one: otherwise the CLI applies the
    // configured default, which is the behaviour they set up deliberately.
    if (root.targetCalendar !== "" && !(root.parsed && root.parsed.calendar))
      command = command.concat(["--calendar", root.targetCalendar])
    addProc.command = command
    addProc.running = true
    if (keepOpen) {
      root.text = ""
      root.parsed = null
    } else {
      root.close()
    }
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
      onStreamFinished: if (text.trim() !== "") root.parseError = text.trim()
    }
    onExited: {
      root.busy = false
      if (root.pendingText !== "") {
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
        var title = ""
        try { title = (JSON.parse(text).event || {}).title || "" } catch (e) {}
        root.added(title)
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") console.warn("omagenda quick add:", text.trim())
    }
    onExited: if (root.service) root.service.reload()
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

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Escape) {
            root.close()
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            // Shift+Enter writes and stays open for the next one, which is
            // what you want when emptying a list of things onto a calendar.
            root.submit((event.modifiers & Qt.ShiftModifier) !== 0)
            event.accepted = true
          } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
            root.cycleCalendar()
            event.accepted = true
          } else if (Util.editsFilter(event, root.text)) {
            root.setText(Util.editedFilter(event, root.text))
            event.accepted = true
          } else if (event.text && event.text.length === 1
                     && event.text.charCodeAt(0) >= 32 && event.text.charCodeAt(0) !== 127) {
            root.setText(root.text + event.text)
            event.accepted = true
          }
        }
      }

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
            text: "Lunch with Sarah tomorrow at 1pm…"
            color: root.foreground
            opacity: 0.45
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
          }

          Row {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0

            Text {
              id: field
              width: Math.min(implicitWidth, parent.width - caret.width)
              textFormat: Text.StyledText
              text: root.highlighted
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              elide: Text.ElideLeft
            }

            Rectangle {
              id: caret
              width: Math.max(1, Style.space(1))
              height: Style.font.heading
              anchors.verticalCenter: parent.verticalCenter
              color: root.foreground
              visible: root.opened

              SequentialAnimation on opacity {
                running: root.opened
                loops: Animation.Infinite
                NumberAnimation { to: 0; duration: 520 }
                NumberAnimation { to: 1; duration: 520 }
              }
            }
          }
        }

        PanelSeparator { foreground: root.foreground }

        // ---- what will actually be written ------------------------------
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
          visible: root.effectiveCalendar !== ""
          text: "→ " + root.effectiveCalendar
                + (root.parsed && root.parsed.calendar ? "  (from the sentence)" : "")
          color: root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: "ENTER SAVE · SHIFT+ENTER SAVE AND ADD ANOTHER · TAB CALENDAR · ESC CANCEL"
          color: Qt.darker(root.foreground, 1.6)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.letterSpacing: 1.0
        }
      }
    }
  }
}
