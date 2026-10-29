import QtQuick
import QtQuick.Layouts
import QtQuick.Effects

Window {
    id: win
    width: 1280
    height: 820
    minimumWidth: 1100
    minimumHeight: 720
    visible: true
    title: "Clippr"
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint

    readonly property bool isWindows: backend.platform === "win10" || backend.platform === "win11"
    readonly property bool maximized: visibility === Window.Maximized || visibility === Window.FullScreen
    property bool chromeless: false          // true while the player is full screen
    property string glassMode: "solid"       // mode actually granted by the OS

    // ---- theme wiring: backend -> Theme singleton ---------------------------------------------------------
    function resolvedTheme() {
        if (backend.themeId !== "auto") return backend.themeId
        return Application.styleHints.colorScheme === Qt.ColorScheme.Light ? "light" : "graphite"
    }
    Binding { target: Theme; property: "themeKey"; value: win.resolvedTheme() }
    Binding { target: Theme; property: "reduceMotion"; value: backend.reduceMotion }
    Binding { target: Theme; property: "fontUi"; value: backend.fontUi }
    Binding { target: Theme; property: "fontMono"; value: backend.fontMono }
    Binding { target: Theme; property: "dark"; value: Theme.p.dark }
    Binding { target: Theme; property: "panelAlpha"; value: win.glassMode === "solid" ? 1.0 : backend.opacity }

    // ---- OS backdrop (acrylic / mica / see-through) ------------------------------------------------------
    // Frost: with Glass and Frost above 0 the app blurs a picture of the desktop itself, so the slider sets the blur
    // amount. (Windows' own acrylic only has one blur strength.) If the picture can't be taken it falls back to acrylic.
    readonly property bool snapshotMode: backend.mode === "glass" && backend.frost > 0 && desktop.available && !desktop.failed
    onSnapshotModeChanged: { applyBackdrop(); if (snapshotMode) desktop.refresh(win) }
    Timer { interval: 2500; repeat: true; running: win.snapshotMode && win.visible && win.visibility !== Window.Minimized; onTriggered: desktop.refresh(win) }
    Timer { id: snapDebounce; interval: 160; onTriggered: if (win.snapshotMode) desktop.refresh(win) }
    onXChanged: snapDebounce.restart()
    onYChanged: snapDebounce.restart()
    onWidthChanged: snapDebounce.restart()
    onHeightChanged: snapDebounce.restart()
    onScreenChanged: snapDebounce.restart()

    property string backdropKey: ""
    function applyBackdrop() {
        // Only touch the OS when something it shows has changed (cheap: after the first call it just updates the tint).
        const hex = String(Theme.p.winS)
        const frost = win.snapshotMode ? 0 : backend.frost   // snapshot mode wants the plain see-through window
        const key = backend.mode + "|" + frost + "|" + hex + "|" + Math.round(backend.opacity * 100)
        if (key === backdropKey) return
        backdropKey = key
        win.glassMode = backend.applyGlass(win, backend.mode, frost, hex, backend.opacity)
    }
    Component.onCompleted: { Theme.started = true; applyBackdrop(); if (snapshotMode) desktop.refresh(win); backend.setSession(backend.session) }
    Connections { target: backend; function onAppearanceChanged() { Qt.callLater(win.applyBackdrop) } }

    // ---- the window surface ------------------------------------------------------------------------------
    Rectangle {
        id: surface
        anchors.fill: parent
        anchors.margins: 0
        // Windows draws its own rounded corners (Win11) so we stay square there; elsewhere we round it ourselves.
        radius: win.isWindows || win.maximized ? 0 : 12
        color: "transparent"
        clip: true
        border.width: win.maximized ? 0 : 1
        border.color: Theme.line

        Item {  // the blurred desktop picture (Frost)
            anchors.fill: parent
            visible: win.snapshotMode && win.glassMode !== "solid"
            clip: true
            layer.enabled: visible
            layer.effect: MultiEffect {
                blurEnabled: true
                blur: backend.frost / 100
                blurMax: 64
                autoPaddingEnabled: false
            }
            Image {
                x: Screen.virtualX - win.x
                y: Screen.virtualY - win.y
                width: Screen.width
                height: Screen.height
                source: "image://desktop/" + desktop.snapId
                cache: false
                smooth: true
                fillMode: Image.Stretch
            }
        }

        Rectangle {  // tint: the window's own color, at the chosen opacity (1 in Solid)
            anchors.fill: parent
            color: Theme.winS
            opacity: win.glassMode === "solid" ? 1.0 : backend.opacity
            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        }

        RowLayout {
            anchors.fill: parent
            spacing: 0

            Sidebar {
                Layout.preferredWidth: 216
                Layout.fillHeight: true
                visible: !win.chromeless
                window: win
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                // empty strip at the top: drag area
                MouseArea {
                    Layout.fillWidth: true
                    Layout.preferredHeight: win.chromeless ? 0 : 14
                    onPressed: win.startSystemMove()
                    onDoubleClicked: win.visibility = win.maximized ? Window.Windowed : Window.Maximized
                }

                StackLayout {
                    id: pages
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: backend.session === "clip" ? 0 : backend.session === "appearance" ? 2 : 1

                    ClipPage {
                        id: clipPage
                        fullscreenPreview: win.chromeless
                        onFullscreenToggled: win.setFullscreenPreview(!win.chromeless)
                    }
                    ToolPage { key: backend.session }
                    AppearancePage {}
                }

                // status line
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: win.chromeless ? 0 : 30
                    color: "transparent"
                    visible: !win.chromeless
                    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }
                    Row {
                        anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter }
                        spacing: 8
                        Rectangle {
                            id: statusDot
                            width: 7; height: 7; radius: 3.5
                            anchors.verticalCenter: parent.verticalCenter
                            color: backend.statusKind === "error" ? Theme.danger : (backend.statusKind === "idle" ? Theme.t3 : Theme.acc)
                            SequentialAnimation on opacity {
                                running: backend.statusKind === "busy" && !Theme.reduceMotion
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.3; duration: 700 }
                                NumberAnimation { to: 1; duration: 700 }
                                onRunningChanged: if (!running) statusDot.opacity = 1
                            }
                        }
                        Text {
                            text: backend.statusText
                            color: backend.statusKind === "error" ? Theme.danger : Theme.t2
                            font.family: Theme.fontUi; font.pixelSize: 12
                            elide: Text.ElideRight
                            width: Math.min(implicitWidth, surface.width - 300)
                        }
                    }
                }
            }
        }

        WindowControls {
            anchors { top: parent.top; right: parent.right }
            z: 20
            visible: !win.chromeless
            window: win
            onCloseRequested: win.tryClose()
        }

        // ---- toast ----------------------------------------------------------------------------------------
        Rectangle {
            id: toastBox
            property string msg: ""
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height - 78
            width: toastText.implicitWidth + 40
            height: 38
            radius: 19
            color: Theme.card2
            border.width: 1
            border.color: Theme.line
            opacity: 0
            scale: 0.92
            Text { id: toastText; anchors.centerIn: parent; text: toastBox.msg; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 13 }
            ParallelAnimation {
                id: toastAnim
                NumberAnimation { target: toastBox; property: "opacity"; to: 1; duration: 200 }
                SpringAnimation { target: toastBox; property: "scale"; to: 1; spring: 5; damping: 0.4 }
            }
            Timer { id: toastTimer; interval: 2800; onTriggered: { toastBox.opacity = 0; toastBox.scale = 0.92 } }
            Behavior on opacity { NumberAnimation { duration: 250 } }
            function show(m) { msg = m; toastAnim.restart(); toastTimer.restart() }
        }
        Connections { target: backend; function onToast(m) { toastBox.show(m) } }

        // ---- quit confirmation sheet --------------------------------------------------------------------
        Rectangle {
            id: sheet
            anchors.fill: parent
            color: "#99000000"
            opacity: 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 180 } }
            MouseArea { anchors.fill: parent }
            Card {
                anchors.centerIn: parent
                width: 380; height: 190
                raised: true
                scale: sheet.opacity > 0.5 ? 1 : 0.9
                Behavior on scale { SpringAnimation { spring: 5; damping: 0.4; epsilon: 0.002 } }
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 8
                    Text { text: "Quit Clippr?"; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 18; font.weight: Font.Bold }
                    Text { Layout.fillWidth: true; text: "A clip is still downloading. Quitting will cancel it."; wrapMode: Text.WordWrap; color: Theme.t2; font.family: Theme.fontUi; font.pixelSize: 13 }
                    Item { Layout.fillHeight: true }
                    RowLayout {
                        spacing: 10
                        Btn { Layout.fillWidth: true; text: "Keep downloading"; onClicked: sheet.opacity = 0 }
                        Btn { Layout.fillWidth: true; text: "Quit"; danger: true; onClicked: Qt.quit() }
                    }
                }
            }
        }
    }

    // ---- window resize grips (frameless) ------------------------------------------------------------------
    component Grip: MouseArea {
        property int edges: 0
        property int cur: Qt.ArrowCursor
        hoverEnabled: true
        cursorShape: cur
        visible: !win.maximized
        onPressed: win.startSystemResize(edges)
    }
    Grip { edges: Qt.LeftEdge; cur: Qt.SizeHorCursor; x: 0; y: 10; width: 5; height: parent.height - 20 }
    Grip { edges: Qt.RightEdge; cur: Qt.SizeHorCursor; x: parent.width - 5; y: 10; width: 5; height: parent.height - 20 }
    Grip { edges: Qt.TopEdge; cur: Qt.SizeVerCursor; x: 10; y: 0; width: parent.width - 20; height: 5 }
    Grip { edges: Qt.BottomEdge; cur: Qt.SizeVerCursor; x: 10; y: parent.height - 5; width: parent.width - 20; height: 5 }
    Grip { edges: Qt.LeftEdge | Qt.TopEdge; cur: Qt.SizeFDiagCursor; x: 0; y: 0; width: 10; height: 10 }
    Grip { edges: Qt.RightEdge | Qt.TopEdge; cur: Qt.SizeBDiagCursor; x: parent.width - 10; y: 0; width: 10; height: 10 }
    Grip { edges: Qt.LeftEdge | Qt.BottomEdge; cur: Qt.SizeBDiagCursor; x: 0; y: parent.height - 10; width: 10; height: 10 }
    Grip { edges: Qt.RightEdge | Qt.BottomEdge; cur: Qt.SizeFDiagCursor; x: parent.width - 10; y: parent.height - 10; width: 10; height: 10 }

    // ---- actions -------------------------------------------------------------------------------------------
    function tryClose() {
        if (backend.requestClose()) Qt.quit()
        else sheet.opacity = 1
    }
    onClosing: (close) => { if (!backend.requestClose()) { close.accepted = false; sheet.opacity = 1 } }

    function setFullscreenPreview(on) {
        chromeless = on
        visibility = on ? Window.FullScreen : Window.Windowed
    }

    // links dropped onto the window load the video
    DropArea {
        anchors.fill: parent
        keys: ["text/uri-list", "text/plain"]
        onDropped: (d) => {
            if (backend.session === "mp3") { tools.addLinks(d.hasText ? d.text : d.urls.join("\n")); return }
            if (backend.session === "convert" || backend.session === "resize" || backend.session === "compress") {
                if (d.hasUrls) tools.addPaths(d.urls.map(u => u.toString()))
                return
            }
            if (backend.session !== "clip") return
            if (d.hasUrls && d.urls.length > 0 && d.urls[0].toString().startsWith("file:")) { backend.loadFile(d.urls[0].toString()); return }
            const link = d.hasUrls && d.urls.length > 0 ? d.urls[0].toString() : d.text
            if (link) backend.loadUrl(link.trim())
        }
    }

    // a click outside a text box takes the keyboard back, so Space, I, O and the arrows work again
    TapHandler {
        acceptedButtons: Qt.LeftButton
        onTapped: (pt) => {
            const it = win.activeFocusItem
            if (it && it.hasOwnProperty("cursorPosition")) {
                let n = it
                for (let i = 0; i < 4 && n; i++, n = n.parent) {
                    const p = n.mapFromItem(null, pt.scenePosition.x, pt.scenePosition.y)
                    if (p.x >= 0 && p.y >= 0 && p.x <= n.width && p.y <= n.height) return
                }
            }
            win.contentItem.forceActiveFocus()
        }
    }
    // once a video has loaded the link box lets go of the keyboard
    Connections {
        target: backend
        function onStateChanged() { if (win.videoReady && win.typing && backend.session === "clip") win.contentItem.forceActiveFocus() }
    }

    // ---- keyboard shortcuts (single-key ones pause while a text field has focus) -----------------------------
    readonly property bool typing: activeFocusItem !== null && activeFocusItem.hasOwnProperty("cursorPosition")
    readonly property bool onClip: backend.session === "clip"
    readonly property bool videoReady: onClip && (backend.state === "ready" || backend.state === "done")

    Shortcut { sequence: "Ctrl+1"; onActivated: backend.setSession("clip") }
    Shortcut { sequence: "Ctrl+2"; onActivated: backend.setSession("mp3") }
    Shortcut { sequence: "Ctrl+3"; onActivated: backend.setSession("convert") }
    Shortcut { sequence: "Ctrl+4"; onActivated: backend.setSession("resize") }
    Shortcut { sequence: "Ctrl+5"; onActivated: backend.setSession("compress") }
    Shortcut { sequence: "Ctrl+V"; enabled: backend.session === "mp3" && !win.typing; onActivated: tools.pasteLinks() }
    Shortcut { sequence: "Ctrl+V"; enabled: win.onClip && !win.typing && backend.state !== "downloading"; onActivated: backend.pasteAndLoad() }
    Shortcut { sequence: "Space"; enabled: win.videoReady && !win.typing; onActivated: backend.togglePlay() }
    Shortcut { sequence: "I"; enabled: win.videoReady && !win.typing; onActivated: backend.markStart() }
    Shortcut { sequence: "O"; enabled: win.videoReady && !win.typing; onActivated: backend.markEnd() }
    Shortcut { sequence: "L"; enabled: win.videoReady && !win.typing; onActivated: backend.toggleLoop() }
    Shortcut { sequence: "F"; enabled: win.videoReady && !win.typing; onActivated: win.setFullscreenPreview(!win.chromeless) }
    Shortcut { sequence: "Escape"; enabled: win.chromeless; onActivated: win.setFullscreenPreview(false) }
    Shortcut { sequence: "Left"; enabled: win.videoReady && !win.typing; onActivated: backend.step(-5) }
    Shortcut { sequence: "Right"; enabled: win.videoReady && !win.typing; onActivated: backend.step(5) }
    Shortcut { sequence: "Shift+Left"; enabled: win.videoReady && !win.typing; onActivated: backend.step(-1 / 30) }
    Shortcut { sequence: "Shift+Right"; enabled: win.videoReady && !win.typing; onActivated: backend.step(1 / 30) }
    Shortcut { sequence: "Home"; enabled: win.videoReady && !win.typing; onActivated: backend.seek(backend.startSec) }
    Shortcut { sequence: "End"; enabled: win.videoReady && !win.typing; onActivated: backend.seek(Math.max(backend.startSec, backend.endSec - 0.1)) }
    Shortcut { sequence: "Ctrl+Return"; enabled: win.onClip && backend.canDownload; onActivated: backend.download() }
    Shortcut { sequence: "Ctrl+Enter"; enabled: win.onClip && backend.canDownload; onActivated: backend.download() }
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: backend.openSaveFolder() }
}
