// The agenda panel: a hero for whatever is next, a week-long ticker strip,
// the selected day's agenda, and a footer of key hints.
//
// Composition follows panels/weather/Panel.qml (hero over detail, the same
// KeyboardPanel + PanelKeyCatcher frame, the same open/hotkey lifecycle) and
// panels/clock/Panel.qml (today marking, stepping the visible range without
// a per-item cursor to keep in sync). Nothing here draws its own chrome:
// PanelHero, PanelSeparator, PanelSectionHeader, and PanelActionButton do
// the work, so a theme change repaints this panel with the rest of the
// desktop.
//
// Keys, per PLAN.md §6.2: h/l and Left/Right step days, H/L step a week,
// j/k walk the day's events, Enter expands one, o opens its meeting or
// location, e opens the .ics in $EDITOR, t returns to today, n starts Quick
// Add on the selected day, s syncs, Escape closes. Tab hands off to the
// neighbouring bar panel, which is the shell's own convention (PanelKeyCatcher
// already routes Left/Right to movement, so panel switching lives on Tab
// here exactly as it does in every first-party panel).

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "fixedsupply.omagenda"
  ipcTarget: "fixedsupply.omagenda"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  property bool openedFromHotkey: false

  // The bar tracks the widget mounted in its slot, not this nested panel, so
  // the popout coordinator and switchPanelFrom both have to be handed the
  // widget as this panel's identity.
  readonly property var barIdentity: hostWidget || root

  readonly property var agenda: service ? service.agenda : ({ calendars: [], events: [] })

  // `now` drives the hero's countdown. It ticks every second, but only while
  // the panel is actually on screen.
  property date now: new Date()
  readonly property string todayKey: Model.dateKey(now)
  property string selectedKey: Model.dateKey(new Date())
  property int cursorIndex: 0
  property bool expanded: false

  readonly property string timeFormat: Model.resolveTimeFormat(
    setting("timeFormat", "system"),
    Qt.locale().timeFormat(Locale.ShortFormat).indexOf("AP") === -1)
  readonly property int dayCount: Math.max(3, Math.min(14, parseInt(setting("days", 7), 10) || 7))

  readonly property var days: Model.tickerDays(agenda, todayKey, selectedKey, dayCount)
  readonly property var dayEvents: Model.eventsForDate(agenda, selectedKey)
  readonly property var heroEvent: Model.currentOrNextEvent(agenda, now)
  readonly property var selectedEvent: cursorIndex >= 0 && cursorIndex < dayEvents.length ? dayEvents[cursorIndex] : null

  readonly property string healthProblem: service ? service.healthProblem : ""
  readonly property color foreground: bar ? bar.foreground : Color.popups.text
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  function calendarColor(event) {
    if (!event) return foreground
    return service
      ? service.paletteColor(Model.calendarColorName(agenda, event.calendar), foreground)
      : foreground
  }

  // ---- lifecycle (mirrors panels/weather/Panel.qml) --------------------
  function open() {
    openedFromHotkey = false
    setCenterHoverRevealSuppressed(false)
    resetToToday()
    root.controller.show()
  }

  function openFromHotkey() {
    openedFromHotkey = true
    resetToToday()
    root.controller.show()
    // Set after showing: showing hands the popout coordinator over, and that
    // handoff closes whichever panel was open, which clears the shared flag.
    Qt.callLater(function() {
      if (root.opened) setCenterHoverRevealSuppressed(true)
    })
  }

  function close() {
    setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.openFromHotkey()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && "centerHoverRevealSuppressed" in root.bar)
      root.bar.centerHoverRevealSuppressed = value
  }

  // ---- navigation -------------------------------------------------------
  function resetToToday() {
    now = new Date()
    selectedKey = Model.dateKey(now)
    cursorIndex = 0
    expanded = false
  }

  function stepDay(delta) {
    selectedKey = Model.dateKey(Model.addDays(selectedKey, delta))
    cursorIndex = 0
    expanded = false
  }

  function moveCursor(dx, dy) {
    if (dx !== 0) {
      stepDay(dx)
      return
    }
    if (dayEvents.length === 0) return
    var next = cursorIndex + dy
    if (next < 0) next = 0
    if (next > dayEvents.length - 1) next = dayEvents.length - 1
    cursorIndex = next
    expanded = false
  }

  function openSelected() {
    var event = selectedEvent
    if (!event) return
    var target = (event.conference && event.conference.url) ? event.conference.url : event.url
    if (!target && event.location && /^https?:\/\//.test(event.location)) target = event.location
    if (!target) return
    Quickshell.execDetached(["xdg-open", target])
    root.close()
  }

  function editSelected() {
    var event = selectedEvent
    if (!event || !event.file) return
    Quickshell.execDetached(["omarchy-launch-editor", event.file])
    root.close()
  }

  function quickAdd() {
    // Phase 3 adds the overlay this calls into; until then the key is
    // harmlessly inert rather than mapped to nothing at all.
    if (service && typeof service.quickAdd === "function") {
      service.quickAdd(selectedKey)
      root.close()
    }
  }

  function sync() {
    if (service) service.sync()
  }

  function handleTextKey(text) {
    if (text === "t") resetToToday()
    else if (text === "s") sync()
    else if (text === "n") quickAdd()
    else if (text === "o") openSelected()
    else if (text === "e") editSelected()
    else if (text === "H") stepDay(-7)
    else if (text === "L") stepDay(7)
  }

  Timer {
    // Only while the panel is on screen: a bar-wide countdown does not need
    // second resolution, and the widget already ticks once a minute.
    interval: 1000
    running: root.opened
    repeat: true
    onTriggered: root.now = new Date()
  }

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.openFromHotkey() }
    function close(): void { root.close() }
    function show(): void { root.openFromHotkey() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(agendaColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
      onReturnRequested: root.expanded = !root.expanded
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) { root.handleTextKey(text) }

      Flickable {
        id: agendaScroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: agendaColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: agendaColumn
          width: agendaScroll.width
          spacing: Style.space(12)

          // ---- hero: whatever is running or next -----------------------
          PanelHero {
            id: hero
            title: root.heroEvent ? root.heroEvent.title : "Nothing else today"
            meta: {
              if (!root.heroEvent) {
                var tomorrow = Model.eventsForDate(root.agenda, Model.addDays(root.todayKey, 1))
                return tomorrow.length > 0
                  ? "Tomorrow · " + Model.formatTime(tomorrow[0].start, root.timeFormat) + " " + tomorrow[0].title
                  : "Nothing tomorrow either"
              }
              var when = Model.formatTimeRange(root.heroEvent, root.timeFormat)
              var away = Model.isRunning(root.heroEvent, root.now)
                ? "now"
                : "in " + Model.countdownText(root.heroEvent.start, root.now)
              return when + " · " + away + " · " + Model.calendarName(root.agenda, root.heroEvent.calendar)
            }
            foreground: root.foreground
            fontFamily: root.fontFamily

            iconComponent: Rectangle {
              width: Style.space(3)
              height: Style.space(34)
              radius: width / 2
              color: root.heroEvent ? root.calendarColor(root.heroEvent) : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.25)
            }

            trailingControl: PanelActionButton {
              visible: !!(root.heroEvent && root.heroEvent.conference && root.heroEvent.conference.url)
              iconText: "󰕧"
              tooltipText: root.heroEvent && root.heroEvent.conference
                ? "Join " + (root.heroEvent.conference.provider || "meeting") : ""
              foreground: root.foreground
              hoverColor: Color.accent
              fontFamily: root.fontFamily
              bordered: true
              onClicked: {
                if (!root.heroEvent || !root.heroEvent.conference) return
                Quickshell.execDetached(["xdg-open", root.heroEvent.conference.url])
                root.close()
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ---- ticker: one cell per day, today and the selection marked --
          Row {
            id: ticker
            width: parent.width
            spacing: Style.space(2)

            Repeater {
              model: root.days

              delegate: Item {
                required property var modelData
                width: (ticker.width - (root.days.length - 1) * Style.space(2)) / root.days.length
                height: dayColumn.implicitHeight + Style.space(10)

                BorderSurface {
                  anchors.fill: parent
                  radius: Style.cornerRadius
                  color: modelData.isSelected ? Style.selectedAccentFill : "transparent"
                  borderSpec: modelData.isSelected
                    ? Border.controlSpec("selected", Color.accent, Color.accent)
                    : Border.none()
                }

                Column {
                  id: dayColumn
                  anchors.centerIn: parent
                  spacing: Style.space(2)

                  Text {
                    textFormat: Text.PlainText
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: modelData.weekday
                    color: Qt.darker(root.foreground, 1.4)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.letterSpacing: 0.8
                  }

                  Text {
                    textFormat: Text.PlainText
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: modelData.day
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.subtitle
                    font.bold: modelData.isToday
                  }

                  Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: Style.space(4)
                    spacing: Style.space(2)

                    Repeater {
                      model: modelData.dots
                      delegate: Rectangle {
                        required property var modelData
                        width: Style.space(4)
                        height: Style.space(4)
                        radius: width / 2
                        color: root.service ? root.service.paletteColor(modelData, root.foreground) : root.foreground
                      }
                    }
                  }
                }

                TapHandler {
                  onTapped: {
                    root.selectedKey = modelData.key
                    root.cursorIndex = 0
                    root.expanded = false
                  }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          PanelSectionHeader {
            text: Qt.formatDate(Model.toDate(root.selectedKey), "dddd d MMMM")
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          // ---- the selected day's agenda --------------------------------
          Column {
            width: parent.width
            spacing: Style.space(1)

            Text {
              textFormat: Text.PlainText
              visible: root.dayEvents.length === 0 && root.healthProblem === ""
              width: parent.width
              text: "Nothing scheduled"
              color: Qt.darker(root.foreground, 1.4)
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              topPadding: Style.space(6)
              bottomPadding: Style.space(6)
            }

            // A broken watcher renders an empty agenda that is
            // indistinguishable from a free day, so say what is actually
            // wrong and what to run about it.
            Text {
              textFormat: Text.PlainText
              visible: root.healthProblem !== ""
              width: parent.width
              text: root.healthProblem
              color: Color.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
              topPadding: Style.space(6)
              bottomPadding: Style.space(6)
            }

            Repeater {
              model: root.dayEvents

              delegate: Item {
                id: eventRow
                required property var modelData
                required property int index
                readonly property bool isCursor: index === root.cursorIndex
                readonly property bool isOpen: isCursor && root.expanded

                width: parent.width
                height: rowContent.implicitHeight + Style.space(10)

                BorderSurface {
                  anchors.fill: parent
                  radius: Style.cornerRadius
                  color: eventRow.isCursor ? Style.hoverFill : "transparent"
                  borderSpec: Border.none()
                }

                Row {
                  id: rowContent
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(10)

                  Text {
                    textFormat: Text.PlainText
                    width: Style.space(46)
                    anchors.top: parent.top
                    text: modelData.allDay ? "all day" : Model.formatTime(modelData.start, root.timeFormat)
                    color: Qt.darker(root.foreground, 1.4)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                  }

                  Rectangle {
                    width: Style.space(2)
                    height: rowLabels.implicitHeight
                    radius: width / 2
                    color: root.calendarColor(modelData)
                  }

                  Column {
                    id: rowLabels
                    width: rowContent.width - Style.space(46) - Style.space(2) - Style.space(20)
                    spacing: Style.space(1)

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      text: modelData.title
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      font.bold: eventRow.isCursor
                      elide: Text.ElideRight
                    }

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      visible: text !== ""
                      text: Model.secondLine(modelData, root.agenda)
                      color: Qt.darker(root.foreground, 1.5)
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }

                    // Expanded detail, on Enter: the things that don't earn a
                    // permanent line but are the reason you opened the event.
                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      visible: eventRow.isOpen && text !== ""
                      text: {
                        var bits = []
                        if (modelData.location) bits.push(modelData.location)
                        if (modelData.recurring) bits.push("repeats")
                        if (modelData.attendees) bits.push(modelData.attendees + " attending")
                        if (modelData.description) bits.push(String(modelData.description).split("\n")[0])
                        return bits.join(" · ")
                      }
                      color: Qt.darker(root.foreground, 1.5)
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      wrapMode: Text.WordWrap
                      topPadding: Style.space(3)
                    }
                  }
                }

                TapHandler {
                  onTapped: {
                    root.cursorIndex = eventRow.index
                    root.expanded = !root.expanded
                  }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ---- footer: state on the left, the keys on the right ---------
          Item {
            width: parent.width
            height: footerLeft.implicitHeight

            Text {
              id: footerLeft
              textFormat: Text.PlainText
              anchors.left: parent.left
              text: Model.footerText(root.agenda, root.timeFormat).toUpperCase()
              color: Qt.darker(root.foreground, 1.5)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1.0
            }

            Text {
              textFormat: Text.PlainText
              anchors.right: parent.right
              text: "N NEW · S SYNC · T TODAY"
              color: Qt.darker(root.foreground, 1.6)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1.0
            }
          }
        }
      }
    }
  }
}
