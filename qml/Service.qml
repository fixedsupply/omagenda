// Headless service: the one place agenda.json is read and parsed, the owner
// of the `omagenda watch` process, and the plugin's IPC target.
//
// The bar widget and its panel reach this instance through
// `bar.shell.serviceFor("fixedsupply.omagenda")`, which is how a bar widget
// and a service in the same plugin share state (the pattern njpatel.omapager
// uses). That matters more than it looks: a bar surface exists per monitor,
// so without a single shared owner every screen would parse agenda.json and
// run its own watcher.
//
// See ARCHITECTURE.md §3 (data flow) and §8.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "Model.js" as Model

Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string home: Quickshell.env("HOME")
  readonly property string stateDir: {
    var override = Quickshell.env("OMAGENDA_STATE")
    return override && override !== "" ? override : home + "/.local/state/omagenda"
  }
  readonly property string agendaPath: stateDir + "/agenda.json"
  readonly property string themeColorsPath: home + "/.local/state/omarchy/current/theme/colors.toml"

  // The CLI ships beside this file, so the plugin runs in place from
  // wherever it was cloned without anything on PATH.
  readonly property string binPath: Qt.resolvedUrl("../bin/omagenda").toString().replace(/^file:\/\//, "")

  // Reassigned wholesale on every load, never mutated in place -- that is
  // what makes the widget's and panel's bindings re-evaluate.
  property var agenda: ({ calendars: [], events: [] })
  property var palette: ({})
  property bool watchRunning: false
  property string lastError: ""

  // Ticks once a minute so countdown bindings in the bar have something to
  // depend on. The panel runs its own faster timer only while it is open.
  property int minuteTick: 0

  readonly property int eventCount: agenda && agenda.events ? agenda.events.length : 0

  // The calendar new events go to, as the CLI would resolve it, so Quick
  // Add can show the destination before anything is written.
  property string defaultCalendar: ""

  function reload() {
    agendaFile.reload()
  }

  function sync() {
    if (syncProc.running) return
    syncProc.running = true
  }

  function paletteColor(name, fallback) {
    return Model.paletteColor(root.palette, name, fallback)
  }

  // "" when everything is fine; otherwise a sentence naming what to do.
  readonly property string healthProblem: Model.healthProblem(lastError, eventCount)

  // ---- agenda.json --------------------------------------------------
  FileView {
    id: agendaFile
    path: root.agendaPath
    watchChanges: true
    printErrors: false

    onLoaded: {
      try {
        root.agenda = JSON.parse(text())
        root.lastError = ""
      } catch (e) {
        root.lastError = "agenda.json is not valid JSON: " + e
      }
    }
    onLoadFailed: {
      // Normal before the first index run; the watcher below will write it.
      root.agenda = ({ calendars: [], events: [] })
    }
    onFileChanged: reload()
  }

  // ---- theme palette -------------------------------------------------
  // agenda.json names a calendar's colour ("blue", "green"); the theme
  // decides what that means. The shell's Color singleton only exposes
  // foreground/background/accent/urgent/muted, so the named palette has to
  // come from the theme's own colors.toml -- the same file Color.qml reads.
  FileView {
    id: colorsFile
    path: root.themeColorsPath
    watchChanges: true
    printErrors: false
    onLoaded: root.palette = Model.parsePalette(text())
  }

  // Color.qml loads colors.toml once at startup and gets runtime theme
  // switches pushed to it over IPC, and `current/theme` is a symlink that
  // gets repointed rather than rewritten -- so a file watch alone can miss a
  // theme change. The shell's own accent moving is the reliable signal.
  Connections {
    target: Color
    function onAccentChanged() { colorsFile.reload() }
  }

  // ---- omagenda watch -------------------------------------------------
  // Reindexes on vdir changes and fires alarms. It takes its own lock, so a
  // stale instance from a previous shell can never be double-started.
  Process {
    id: watchProc
    command: [root.binPath, "watch"]
    running: true

    onRunningChanged: root.watchRunning = running
    onExited: function(exitCode, exitStatus) {
      root.watchRunning = false
      if (exitCode !== 0 && root.lastError === "")
        root.lastError = "omagenda watch exited " + exitCode
      // Back off rather than spin: a missing Python dependency would
      // otherwise restart in a tight loop for the life of the session.
      watchRestartTimer.restart()
    }

    // The watcher's own message is the useful one -- "No module named
    // 'icalendar'" tells the user exactly what to install, where a bare
    // exit code tells them nothing. Kept so the pill and panel can say it
    // rather than rendering an empty agenda that looks like a free week.
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var message = text.trim()
        if (message !== "") {
          root.lastError = message
          console.warn("omagenda:", message)
        }
      }
    }
  }

  Timer {
    id: watchRestartTimer
    interval: 10000
    repeat: false
    onTriggered: if (!watchProc.running) watchProc.running = true
  }

  // Read from config.toml rather than guessed, and re-read whenever it
  // changes, so `omagenda calendars --set-default` shows up without a
  // shell restart.
  FileView {
    id: configFile
    path: root.home + "/.config/omagenda/config.toml"
    watchChanges: true
    printErrors: false
    onLoaded: {
      var match = /^\s*default_calendar\s*=\s*"([^"]*)"/m.exec(text())
      root.defaultCalendar = match ? match[1] : ""
    }
    onLoadFailed: root.defaultCalendar = ""
    onFileChanged: reload()
  }

  Process {
    id: syncProc
    command: [root.binPath, "sync"]
    onExited: root.reload()
  }

  Timer {
    interval: 60000
    running: true
    repeat: true
    onTriggered: root.minuteTick++
  }

  // ---- Quick Add -------------------------------------------------------
  // Hosted here rather than declared as an `overlay` kind in the manifest:
  // the shell routes `summon <plugin id>` to the bar widget's panel unless
  // the plugin declares overlay/panel/menu, and declaring one would have
  // stolen `shell toggle` from the agenda panel (shell.qml's
  // isBarWidgetPanelPlugin). Owning the surface here keeps both doors.
  function quickAdd(dateKey) {
    quickAddLoader.active = true
    if (quickAddLoader.item) quickAddLoader.item.open(dateKey || "")
  }

  Loader {
    id: quickAddLoader
    active: false
    source: Qt.resolvedUrl("QuickAdd.qml")
    onLoaded: {
      item.service = root
      item.binPath = root.binPath
      item.added.connect(function(title) {
        Quickshell.execDetached([
          "omarchy-notification-send", "-g", "󰃭", "Added to your calendar", title || "Event"
        ])
        root.reload()
      })
    }
  }

  // ---- IPC -------------------------------------------------------------
  // `omarchy-shell shell toggle fixedsupply.omagenda` opens the agenda panel
  // (the bar-widget route). These are the plugin's own extra verbs, which is
  // also where Quick Add will hang in Phase 3: the shell's generic summon
  // can't reach a second surface in a plugin that already owns a bar widget.
  IpcHandler {
    target: "omagenda"

    function sync(): void { root.sync() }
    function reload(): void { root.reload() }
    function quickAdd(): void { root.quickAdd("") }
    function quickAddOn(dateKey: string): void { root.quickAdd(dateKey) }
    function status(): string {
      return JSON.stringify({
        events: root.eventCount,
        watchRunning: root.watchRunning,
        lastSync: root.agenda && root.agenda.lastSync ? root.agenda.lastSync : null,
        error: root.lastError,
        problem: root.healthProblem
      })
    }
  }
}
