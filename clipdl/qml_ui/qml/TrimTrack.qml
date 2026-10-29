import QtQuick

// A timeline in the style of Clipchamp: a time ruler on top, a video strip and an audio strip below it, and a playhead.
// You trim by dragging the two edges of the clip inward (the parts you cut are dimmed, and you can drag them back out).
// Click or drag on the ruler or the strips to scrub. Scroll to pan; Ctrl + scroll (or the zoom buttons) to zoom.
// Everything is a scene graph item, so dragging stays at the display refresh rate.
Item {
    id: root
    clip: true
    property real duration: backend.duration
    property real startSec: backend.startSec
    property real endSec: backend.endSec
    property real posSec: backend.positionSec
    property var peaks: backend.peaks
    property bool locked: backend.state === "downloading"
    property real sweep: backend.state === "downloading" ? backend.progress : -1
    readonly property bool ready: backend.state === "ready" || backend.state === "done"

    // zoom / pan
    property real zoom: 1
    property real viewStart: 0
    readonly property real viewSpan: duration > 0 ? duration / zoom : 1
    readonly property real maxZoom: Math.max(1, Math.min(60, duration / 2))
    function clampView() {
        viewStart = Math.max(0, Math.min(Math.max(0, duration - viewSpan), viewStart))
    }
    function setZoom(z, anchorT) {
        const nz = Math.max(1, Math.min(maxZoom, z))
        const frac = viewSpan > 0 ? (anchorT - viewStart) / viewSpan : 0
        zoom = nz
        viewStart = anchorT - frac * viewSpan
        clampView()
    }
    function zoomBy(f) { setZoom(zoom * f, posSec >= viewStart && posSec <= viewStart + viewSpan ? posSec : viewStart + viewSpan / 2) }
    function fit() { zoom = 1; viewStart = 0 }
    onDurationChanged: { zoom = 1; viewStart = 0 }
    Behavior on zoom { enabled: !wheelZoom.active; NumberAnimation { duration: Theme.reduceMotion ? 0 : 180; easing.type: Easing.OutCubic } }
    Behavior on viewStart { enabled: !pan.active && !drag.pressed; NumberAnimation { duration: Theme.reduceMotion ? 0 : 160; easing.type: Easing.OutCubic } }
    onPosSecChanged: {  // follow the playhead while zoomed in
        if (zoom > 1.01 && !drag.pressed && backend.playing) {
            if (posSec > viewStart + viewSpan * 0.94 || posSec < viewStart) { viewStart = posSec - viewSpan * 0.08; clampView() }
        }
    }

    // layout
    readonly property real pad: 12
    readonly property real usable: Math.max(1, width - pad * 2)
    readonly property real rulerH: 26
    readonly property real videoY: rulerH + 4
    readonly property real videoH: 46
    readonly property real audioY: videoY + videoH + 4
    readonly property real audioH: 34
    implicitHeight: audioY + audioH + 6

    function t2x(t) { return pad + (t - viewStart) / viewSpan * usable }
    function x2t(x) { return duration > 0 ? Math.max(0, Math.min(duration, viewStart + (x - pad) / usable * viewSpan)) : 0 }
    function fmt(t, fine) {
        const s = Math.max(0, t)
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
        const frac = fine ? "." + Math.round((s - Math.floor(s)) * 10 % 10) : ""
        const ss = (sec < 10 ? "0" : "") + sec
        return h > 0 ? h + ":" + (m < 10 ? "0" : "") + m + ":" + ss + frac : m + ":" + ss + frac
    }

    // ---- ruler ----------------------------------------------------------------------------------------------
    readonly property var steps: [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]
    readonly property real tickStep: {
        for (let i = 0; i < steps.length; i++) if (steps[i] / viewSpan * usable >= 78) return steps[i]
        return steps[steps.length - 1]
    }
    Item {
        id: ruler
        width: parent.width
        height: root.rulerH
        clip: true
        Repeater {
            model: Math.ceil(root.viewSpan / root.tickStep) + 3
            delegate: Item {
                required property int index
                readonly property real t: (Math.floor(root.viewStart / root.tickStep) + index) * root.tickStep
                x: root.t2x(t)
                visible: t >= -0.001 && t <= root.duration + 0.001
                Rectangle { x: -0.5; y: root.rulerH - 9; width: 1; height: 9; color: Theme.t3 }
                Text {
                    x: 4; y: 2
                    text: root.fmt(parent.t, root.tickStep < 1)
                    color: Theme.t3
                    font.family: Theme.fontMono; font.pixelSize: 10
                }
                Rectangle {  // minor tick
                    x: root.t2x(parent.t + root.tickStep / 2) - root.t2x(parent.t) - 0.5
                    y: root.rulerH - 5; width: 1; height: 5
                    color: Theme.alpha(Theme.t3, 0.55)
                }
            }
        }
    }

    // ---- video strip (thumbnail tiles) and audio strip (waveform) ---------------------------------------------
    readonly property real blockX: t2x(0)
    readonly property real blockW: duration > 0 ? t2x(duration) - t2x(0) : usable

    component Lane: Rectangle {
        x: root.blockX
        width: root.blockW
        radius: 9
        clip: true
        border.width: 1
        border.color: Theme.line
    }

    Lane {
        id: videoLane
        y: root.videoY
        height: root.videoH
        color: Theme.card2A
        readonly property real tileW: Math.round(root.videoH * 16 / 9)
        readonly property int first: Math.max(0, Math.floor((-root.blockX + 0) / tileW))
        Repeater {
            model: Math.min(400, Math.ceil(root.width / videoLane.tileW) + 2)
            delegate: Image {
                required property int index
                x: (videoLane.first + index) * videoLane.tileW
                width: videoLane.tileW
                height: videoLane.height
                source: backend.thumbnail
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                sourceSize.height: 96
                opacity: status === Image.Ready ? 0.92 : 0
                Behavior on opacity { NumberAnimation { duration: 240 } }
            }
        }
        Rectangle { anchors.fill: parent; color: Theme.alpha(Theme.card, 0.12) }
    }

    Lane {
        id: audioLane
        y: root.audioY
        height: root.audioH
        color: Theme.card2A

        readonly property int n: root.peaks && root.peaks.length > 0 ? root.peaks.length : 160
        function barH(i) {
            const v = root.peaks && root.peaks.length > 0 ? root.peaks[i]
                      : 0.16 + 0.1 * Math.abs(Math.sin(i * 0.37) * Math.cos(i * 0.11))
            return Math.max(2, v * (height - 8))
        }
        component Bars: Item {
            property color barColor: "white"
            width: audioLane.width; height: audioLane.height
            Repeater {
                model: audioLane.n
                delegate: Rectangle {
                    required property int index
                    readonly property real slot: audioLane.width / audioLane.n
                    x: index * slot
                    width: Math.max(1.2, slot - 1.2)
                    height: audioLane.barH(index)
                    y: (audioLane.height - height) / 2
                    radius: width / 2
                    color: parent.barColor
                }
            }
        }
        Bars { barColor: Theme.alpha(Theme.t3, 0.55) }
        Item {  // bright part, only inside the kept range
            x: root.t2x(root.startSec) - root.blockX
            width: Math.max(0, root.t2x(root.endSec) - root.t2x(root.startSec))
            height: parent.height
            clip: true
            Bars { x: -parent.x; barColor: Theme.acc }
        }
    }

    // ---- dim the cut-away parts -------------------------------------------------------------------------------
    Rectangle {
        x: root.blockX; y: root.videoY
        width: Math.max(0, root.t2x(root.startSec) - root.blockX)
        height: root.audioY + root.audioH - root.videoY
        radius: 9
        color: "#99000000"
        Behavior on width { enabled: !drag.pressed; NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
    }
    Rectangle {
        x: root.t2x(root.endSec); y: root.videoY
        width: Math.max(0, root.blockX + root.blockW - root.t2x(root.endSec))
        height: root.audioY + root.audioH - root.videoY
        radius: 9
        color: "#99000000"
        Behavior on x { enabled: !drag.pressed; NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
    }

    // ---- kept clip: accent frame with the two trim handles ---------------------------------------------------------
    Item {
        id: clip
        x: root.t2x(root.startSec)
        y: root.videoY - 2
        width: Math.max(8, root.t2x(root.endSec) - root.t2x(root.startSec))
        height: root.audioY + root.audioH - root.videoY + 4
        Behavior on x { enabled: !drag.pressed; NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
        Behavior on width { enabled: !drag.pressed; NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }

        Rectangle {  // frame
            anchors.fill: parent
            radius: 10
            color: "transparent"
            border.width: 3
            border.color: Theme.acc
        }
        Rectangle {  // download sweep
            visible: root.sweep >= 0
            x: 3; y: 3
            width: Math.max(0, (parent.width - 6) * Math.max(0, root.sweep))
            height: parent.height - 6
            radius: 7
            color: Theme.alpha(Theme.acc, 0.28)
            Behavior on width { NumberAnimation { duration: 140 } }
        }
        Repeater {  // handle caps
            model: 2
            delegate: Rectangle {
                id: cap
                required property int index
                readonly property bool isStart: index === 0
                readonly property bool active: drag.pressed && drag.mode === (isStart ? "start" : "end")
                width: Math.max(7, Math.min(14, clip.width / 3))
                height: parent.height
                x: isStart ? 0 : parent.width - width
                radius: 8
                color: Theme.acc
                scale: active ? 1.06 : 1
                Behavior on scale { SpringAnimation { spring: 5; damping: 0.4; epsilon: 0.002 } }
                Column {
                    visible: parent.width >= 12
                    anchors.centerIn: parent
                    spacing: 3
                    Repeater { model: 3; Rectangle { width: 2; height: 14; radius: 1; color: Theme.accText; opacity: 0.55 } }
                }
                Rectangle {  // time bubble while dragging
                    visible: cap.active
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: -height - 6
                    width: bubble.implicitWidth + 16; height: 22; radius: 11
                    color: Theme.text
                    Text {
                        id: bubble
                        anchors.centerIn: parent
                        text: backend.fmtTenths(cap.isStart ? root.startSec : root.endSec)
                        color: Theme.winS
                        font.family: Theme.fontMono; font.pixelSize: 11; font.weight: Font.DemiBold
                    }
                }
            }
        }
        // clip length badge on the strip
        Rectangle {
            visible: clip.width > 120
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 8 }
            width: lenText.implicitWidth + 14; height: 20; radius: 10
            color: "#aa000000"
            Text { id: lenText; anchors.centerIn: parent; text: backend.fmtTenths(root.endSec - root.startSec); color: "white"; font.family: Theme.fontMono; font.pixelSize: 11 }
        }
    }

    // ---- magnetic snapping (like a DAW; hold Alt to move freely) ------------------------------------------------------
    property real snapAt: -1
    readonly property real snapPx: 9
    function snapTo(t, cands, mods) {
        if (mods & Qt.AltModifier) return { v: t, at: -1 }
        const pps = Math.abs(t2x(1) - t2x(0))
        if (pps <= 0) return { v: t, at: -1 }
        let best = t, at = -1, bd = snapPx / pps
        for (let i = 0; i < cands.length; i++) {
            const d = Math.abs(cands[i] - t)
            if (d <= bd) { bd = d; best = cands[i]; at = cands[i] }
        }
        return { v: best, at: at }
    }

    // ---- in / out markers on the ruler ---------------------------------------------------------------------------------
    Repeater {
        model: root.ready ? 2 : 0
        Item {
            id: mk
            required property int index
            readonly property bool isIn: index === 0
            readonly property real px: root.t2x(isIn ? root.startSec : root.endSec)
            visible: px >= root.pad - 2 && px <= root.width - root.pad + 2
            x: px
            z: 4
            Rectangle {
                x: mk.isIn ? 0 : -width
                y: 2
                width: mkText.implicitWidth + 10; height: 15
                radius: 4
                color: Theme.acc
                Text { id: mkText; anchors.centerIn: parent; text: mk.isIn ? "IN" : "OUT"; color: Theme.accText; font.family: Theme.fontMono; font.pixelSize: 9; font.weight: Font.Bold }
            }
        }
    }

    // ---- snap guide (shows what the drag just locked onto) ---------------------------------------------------------------
    Rectangle {
        visible: root.snapAt >= 0 && drag.pressed
        x: root.t2x(root.snapAt) - 1
        y: root.rulerH - 8
        width: 2; height: root.height - root.rulerH + 8
        radius: 1
        color: Theme.acc
        z: 6
        Rectangle { anchors.centerIn: parent; width: 10; height: parent.height; radius: 5; color: Theme.acc; opacity: 0.22 }
    }

    // ---- playhead ---------------------------------------------------------------------------------------------------
    Item {
        id: head
        readonly property real px: root.t2x(root.posSec)
        visible: root.ready && px >= root.pad - 2 && px <= root.width - root.pad + 2
        x: px
        z: 5
        Rectangle { x: -1; y: root.rulerH - 6; width: 2; height: root.height - root.rulerH + 6; radius: 1; color: Theme.text }
        Rectangle {  // flag on the ruler
            x: -7; y: 3; width: 14; height: 17; radius: 4
            color: Theme.text
            Rectangle { x: 3; y: 12; width: 8; height: 8; rotation: 45; color: Theme.text; z: -1 }
        }
    }

    // ---- input ------------------------------------------------------------------------------------------------------
    MouseArea {
        id: drag
        anchors.fill: parent
        hoverEnabled: true
        enabled: !root.locked && root.duration > 0
        property string mode: ""
        readonly property real grab: 14
        cursorShape: {
            if (mode === "start" || mode === "end") return Qt.SizeHorCursor
            if (containsMouse && mouseY > root.rulerH) {
                const xs = root.t2x(root.startSec), xe = root.t2x(root.endSec)
                if ((mouseX >= xs - 6 && mouseX <= xs + grab) || (mouseX <= xe + 6 && mouseX >= xe - grab)) return Qt.SizeHorCursor
            }
            if (mode === "move") return Qt.ClosedHandCursor
            if (containsMouse && mouseY > root.rulerH && mouseX > root.t2x(root.startSec) && mouseX < root.t2x(root.endSec)) return Qt.OpenHandCursor
            return Qt.PointingHandCursor
        }
        function pick(mx, my) {
            if (my <= root.rulerH) return "seek"
            const xs = root.t2x(root.startSec), xe = root.t2x(root.endSec)
            const inS = mx >= xs - 6 && mx <= xs + grab
            const inE = mx <= xe + 6 && mx >= xe - grab
            if (inS && inE) return Math.abs(mx - xs) <= Math.abs(mx - xe) ? "start" : "end"
            if (inS) return "start"
            if (inE) return "end"
            if (mx > xs && mx < xe) return "move"
            return "seek"
        }
        property real grabOffset: 0
        property real clipLen: 0
        property real pressX: 0
        property bool moved: false
        property real pressPos: 0   // where the playhead was when the drag began (the handles drag it along, so we freeze it)
        onPressed: (m) => {
            pressPos = root.posSec
            mode = pick(m.x, m.y)
            pressX = m.x
            moved = false
            if (mode === "move") { grabOffset = root.x2t(m.x) - root.startSec; clipLen = root.endSec - root.startSec }
            if (mode === "seek") { backend.setScrubbing(true); const r0 = root.snapTo(root.x2t(m.x), [root.startSec, root.endSec, 0, root.duration], m.modifiers); root.snapAt = r0.at; backend.seek(r0.v) }
        }
        onPositionChanged: (m) => {
            if (!pressed) return
            const t = root.x2t(m.x)
            const mods = m.modifiers
            if (mode === "start") {
                const r = root.snapTo(t, [pressPos, 0], mods)
                root.snapAt = r.at
                backend.setRange(Math.min(r.v, root.endSec - 0.2), root.endSec)
            } else if (mode === "end") {
                const r = root.snapTo(t, [pressPos, root.duration], mods)
                root.snapAt = r.at
                backend.setRange(root.startSec, Math.max(r.v, root.startSec + 0.2))
            } else if (mode === "move") {
                if (!moved && Math.abs(m.x - pressX) < 3) return
                moved = true
                let s = t - grabOffset
                const a = root.snapTo(s, [pressPos, 0], mods)
                const b = root.snapTo(s + clipLen, [pressPos, root.duration], mods)
                const da = a.at >= 0 ? Math.abs(a.v - s) : 1e9, db = b.at >= 0 ? Math.abs(b.v - (s + clipLen)) : 1e9
                if (da <= db && a.at >= 0) { s = a.v; root.snapAt = a.at }
                else if (b.at >= 0) { s = b.v - clipLen; root.snapAt = b.at }
                else root.snapAt = -1
                s = Math.max(0, Math.min(root.duration - clipLen, s))
                backend.setRange(s, s + clipLen)
                if (root.zoom > 1.01) {  // edge auto-pan while dragging a zoomed timeline
                    if (m.x > root.width - 24) { root.viewStart += root.viewSpan * 0.02; root.clampView() }
                    else if (m.x < 24) { root.viewStart -= root.viewSpan * 0.02; root.clampView() }
                }
            } else if (mode === "seek") {
                const r = root.snapTo(t, [root.startSec, root.endSec, 0, root.duration], mods)
                root.snapAt = r.at
                backend.seek(r.v)
                // edge auto-pan while scrubbing a zoomed timeline
                if (root.zoom > 1.01) {
                    if (m.x > root.width - 24) { root.viewStart += root.viewSpan * 0.02; root.clampView() }
                    else if (m.x < 24) { root.viewStart -= root.viewSpan * 0.02; root.clampView() }
                }
            }
        }
        onReleased: (m) => {
            if (mode === "move" && !moved) backend.seek(root.x2t(m.x))  // a plain click in the middle still scrubs
            backend.setScrubbing(false); mode = ""; root.snapAt = -1
        }
    }

    // scroll to pan, Ctrl + scroll to zoom around the pointer
    WheelHandler {
        id: wheelZoom
        acceptedModifiers: Qt.ControlModifier
        onWheel: (e) => {
            const f = e.angleDelta.y > 0 ? 1.25 : 0.8
            root.setZoom(root.zoom * f, root.x2t(point.position.x))
        }
    }
    WheelHandler {
        id: pan
        acceptedModifiers: Qt.NoModifier
        onWheel: (e) => {
            if (root.zoom <= 1.01) return
            const d = (Math.abs(e.angleDelta.x) > Math.abs(e.angleDelta.y) ? e.angleDelta.x : -e.angleDelta.y)
            root.viewStart += d / 120 * root.viewSpan * 0.12
            root.clampView()
        }
    }
}
