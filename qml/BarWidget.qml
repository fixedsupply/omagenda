// The Up Next pill, and the host for the agenda panel behind it.
//
// The pill takes a slot only when there is something worth saying: an event
// inside `leadMinutes`, or one running now. That is Omarchy's own convention
// for bar status -- appear when there is state to report -- and it keeps the
// bar's centre from carrying a permanent "nothing scheduled". `alwaysShow`
// holds the slot open for anyone who would rather trade that for a clock
// that never shifts.
//
// Structure follows plugins/panels/weather/BarWidget.qml: a Loader hosts the
// panel, and the widget forwards the open/close/opened shape the bar's
// popout coordinator identifies a panel by.

import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "fixedsupply.omagenda"

  // The service owns agenda.json and the watcher; everything here degrades
  // to an empty agenda rather than breaking the bar if it isn't up.
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor("fixedsupply.omagenda") : null
  readonly property var agenda: service ? service.agenda : ({ calendars: [], events: [] })

  // Countdowns have to re-evaluate without the user touching anything. The
  // service ticks once a minute; this widget re-reads the clock on that tick.
  readonly property int minuteTick: service ? service.minuteTick : 0
  property date now: new Date()

  readonly property int leadMinutes: parseInt(setting("leadMinutes", 30), 10)
  readonly property bool alwaysShow: setting("alwaysShow", false) === true
  readonly property bool showCountdown: setting("showCountdown", true) === true
  readonly property string timeFormat: Model.resolveTimeFormat(
    setting("timeFormat", "system"),
    Qt.locale().timeFormat(Locale.ShortFormat).indexOf("AP") === -1)

  readonly property string label: Model.pillText(agenda, now, {
    leadMinutes: leadMinutes,
    alwaysShow: alwaysShow,
    showCountdown: showCountdown,
    timeFormat: timeFormat
  })

  onMinuteTickChanged: now = new Date()

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    if ("service" in target) target.service = root.service
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  function sync() {
    if (root.service) root.service.sync()
  }

  // Shape contract for shell.summon/hide/toggle routing: Bar.findPanelWidget
  // requires open/close/opened on the bar-widget root, and the popout
  // coordinator compares against this widget rather than the nested panel.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  // Out of the bar entirely when there is nothing to report, unless the
  // panel is open (leaving no way back to it) or the user pinned the slot.
  //
  // Collapsing the width to zero is what takes the slot back, NOT `visible`
  // on this root: hiding the root leaves the bar holding a stale position
  // for it, and the pill then paints over its neighbour (it drew straight
  // through the clock). njpatel.omapager, the other widget that comes and
  // goes, collapses its width for the same reason.
  readonly property bool revealed: label !== "" || opened
  implicitWidth: revealed ? button.implicitWidth : 0
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()
  onServiceChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  // WidgetButton, not BarIconButton: the latter pins its width to a square
  // icon slot, which a text pill immediately overflows -- it drew straight
  // over the clock. This is the component the clock's own label uses, and it
  // sizes to its text.
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.vertical ? "" : root.label
    labelVisible: !root.vertical && root.revealed
    hasVisualContent: root.revealed
    horizontalMargin: 8.75
    verticalPadding: 8.75
    // The panel is the detail view; a tooltip repeating the pill would be
    // noise on hover.
    tooltipText: ""

    onPressed: function(b) {
      if (b === Qt.RightButton || b === Qt.MiddleButton) root.sync()
      else root.togglePanel()
    }

    // A vertical bar has no room for a sentence, so the pill collapses to
    // the calendar glyph and the panel carries the detail.
    Text {
      visible: root.vertical && root.label !== ""
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: "󰃭"
      color: button.foreground
      font.family: button.fontFamily
      font.pixelSize: Style.bar.iconFont
    }
  }
}
