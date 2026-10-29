import QtQuick
import QtQuick.Layouts
import QtMultimedia
import QtQuick.Effects

// Video preview. Frames go from QMediaPlayer straight into a VideoOutput (GPU texture), so playback and the
// overlay animations run on the render thread at the display refresh rate.
Rectangle {
    id: root
    property bool fullscreenMode: false
    signal fullscreenToggled()

    radius: Theme.radiusCard
    color: hasVideo ? "#000000" : Theme.cardA
    border.width: 1
    border.color: Theme.line

    readonly property bool hasVideo: backend.state === "ready" || backend.state === "done"
                                     || backend.state === "downloading" || backend.state === "error"
    readonly property bool showChrome: hover.hovered || !backend.playing || scrubArea.pressed

    // everything lives in clipBox so it can be masked to the rounded corners (GPU mask, no software clipping)
    Item {
        id: clipBox
        anchors.fill: parent
        layer.enabled: GraphicsInfo.api !== GraphicsInfo.Software   // rounded GPU mask (not available in software mode)
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: maskShape
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }

        VideoOutput {
            id: vo
            anchors.fill: parent
            fillMode: VideoOutput.PreserveAspectFit
            visible: root.hasVideo && backend.hasPreview
            Component.onCompleted: backend.attachVideoSink(vo.videoSink)
        }
        Image {  // thumbnail until the first frame (or when there is no preview stream)
            anchors.fill: parent
            source: backend.thumbnail
            id: thumb
            fillMode: Image.PreserveAspectFit
            visible: root.hasVideo && !backend.playing
            opacity: backend.hasPreview ? 0 : 1
            asynchronous: true
        }

        // crop guide: shows which part of the picture a size preset keeps
        Item {
            id: guide
            anchors.fill: parent
            visible: root.hasVideo && backend.aspectValue !== "src" && backend.isVideoFormat
            readonly property var parts: backend.aspectValue.split(":")
            readonly property real a: parts.length === 2 ? parts[0] / parts[1] : 1
            readonly property rect cr: backend.hasPreview && vo.contentRect.width > 0 ? vo.contentRect
                : Qt.rect((width - thumb.paintedWidth) / 2, (height - thumb.paintedHeight) / 2, thumb.paintedWidth, thumb.paintedHeight)
            readonly property real srcA: cr.height > 0 ? cr.width / cr.height : 1
            readonly property real cw: a < srcA ? cr.height * a : cr.width
            readonly property real ch: a < srcA ? cr.height : cr.width / a
            readonly property real slackX: Math.max(0, cr.width - cw)
            readonly property real slackY: Math.max(0, cr.height - ch)
            property real gx: cr.x + slackX * backend.cropX
            property real gy: cr.y + slackY * backend.cropY
            property real gw: cw
            property real gh: ch
            Behavior on gx { enabled: !crop.pressed; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            Behavior on gy { enabled: !crop.pressed; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            Behavior on gw { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            Behavior on gh { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            Rectangle { x: guide.cr.x; y: guide.cr.y; width: Math.max(0, guide.gx - guide.cr.x); height: guide.cr.height; color: "#a6000000" }
            Rectangle { x: guide.gx + guide.gw; y: guide.cr.y; width: Math.max(0, guide.cr.x + guide.cr.width - guide.gx - guide.gw); height: guide.cr.height; color: "#a6000000" }
            Rectangle { x: guide.gx; y: guide.cr.y; width: guide.gw; height: Math.max(0, guide.gy - guide.cr.y); color: "#a6000000" }
            Rectangle { x: guide.gx; y: guide.gy + guide.gh; width: guide.gw; height: Math.max(0, guide.cr.y + guide.cr.height - guide.gy - guide.gh); color: "#a6000000" }
            Rectangle { x: guide.gx; y: guide.gy; width: guide.gw; height: guide.gh; color: "transparent"; border.width: 2; border.color: Theme.acc; radius: 4 }
            // drag the box to choose which part of the picture is kept (double-click centres it)
            MouseArea {
                id: crop
                x: guide.gx; y: guide.gy; width: guide.gw; height: guide.gh
                enabled: guide.slackX > 1 || guide.slackY > 1
                hoverEnabled: true
                cursorShape: pressed ? Qt.ClosedHandCursor : (guide.slackX > 1 ? Qt.SizeHorCursor : Qt.SizeVerCursor)
                property point p0: Qt.point(0, 0)
                property real cx0: 0.5
                property real cy0: 0.5
                property bool moved: false
                onPressed: (m) => { p0 = mapToItem(guide, m.x, m.y); cx0 = backend.cropX; cy0 = backend.cropY; moved = false }
                onPositionChanged: (m) => {
                    if (!pressed) return
                    const p = mapToItem(guide, m.x, m.y)
                    if (Math.abs(p.x - p0.x) + Math.abs(p.y - p0.y) > 3) moved = true
                    const nx = guide.slackX > 1 ? Math.max(0, Math.min(1, cx0 + (p.x - p0.x) / guide.slackX)) : 0.5
                    const ny = guide.slackY > 1 ? Math.max(0, Math.min(1, cy0 + (p.y - p0.y) / guide.slackY)) : 0.5
                    backend.setCropPos(nx, ny)
                }
                onClicked: if (!moved) backend.togglePlay()
                onDoubleClicked: backend.setCropPos(0.5, 0.5)
                Accessible.name: "Crop box. Drag to choose which part of the picture is kept."
            }
            Rectangle {
                x: guide.gx + 8; y: guide.gy + 8
                width: gl.implicitWidth + 14; height: 22; radius: 11
                color: "#b0000000"
                Text { id: gl; anchors.centerIn: parent; text: backend.aspectValue + ((guide.slackX > 1 || guide.slackY > 1) ? "  ·  drag to move" : ""); color: "white"; font.family: Theme.fontMono; font.pixelSize: 11; font.weight: Font.DemiBold }
            }
        }

        // ---- empty / loading states
        Item {
            anchors.fill: parent
            visible: !root.hasVideo
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0; color: Theme.alpha(Theme.acc, 0.10) }
                    GradientStop { position: 1; color: "transparent" }
                }
            }
            Column {
                anchors.centerIn: parent
                spacing: 14
                visible: backend.state === "empty"
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 72; height: 72; radius: 22
                    color: Theme.accSoft
                    Icon { anchors.centerIn: parent; d: Icons.link; size: 30; color: Theme.acc }
                    SequentialAnimation on scale {
                        running: backend.state === "empty" && !Theme.reduceMotion
                        loops: Animation.Infinite
                        NumberAnimation { to: 1.06; duration: 1400; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 1400; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Paste a link to begin"
                    color: Theme.text
                    font.family: Theme.fontUi; font.pixelSize: 20; font.weight: Font.DemiBold
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "YouTube, Instagram or X. You can also drop a link onto the window."
                    color: Theme.t2
                    font.family: Theme.fontUi; font.pixelSize: 13
                }
                Btn {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Paste from clipboard"
                    primary: true
                    onClicked: backend.pasteAndLoad()
                }
            }
            Column {  // loading skeleton
                anchors.centerIn: parent
                spacing: 12
                visible: backend.state === "loading"
                Rectangle {
                    width: 56; height: 56; radius: 28
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: "transparent"
                    border.width: 4
                    border.color: Theme.alpha(Theme.acc, 0.25)
                    Rectangle {
                        anchors.fill: parent; radius: 28; color: "transparent"
                        border.width: 4; border.color: "transparent"
                    }
                    Canvas {
                        anchors.fill: parent
                        onPaint: {
                            const c = getContext("2d"); c.reset()
                            c.strokeStyle = Theme.acc; c.lineWidth = 4; c.lineCap = "round"
                            c.beginPath(); c.arc(28, 28, 26, 0, Math.PI * 0.6); c.stroke()
                        }
                        RotationAnimator on rotation { from: 0; to: 360; duration: 900; loops: Animation.Infinite; running: backend.state === "loading" }
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Loading video…"
                    color: Theme.t2
                    font.family: Theme.fontUi; font.pixelSize: 14
                }
            }
        }

        Text {  // no-preview message
            anchors.centerIn: parent
            visible: root.hasVideo && !backend.hasPreview
            text: backend.hasMultimedia ? "No preview stream for this video. Trimming still works."
                                        : "Preview isn't available (Qt Multimedia missing). Trimming still works."
            color: "#ffffff"
            font.family: Theme.fontUi; font.pixelSize: 13
            style: Text.Outline; styleColor: "#99000000"
        }

        HoverHandler { id: hover; enabled: root.hasVideo }
        TapHandler {
            enabled: root.hasVideo && backend.hasPreview
            onTapped: backend.togglePlay()
            onDoubleTapped: root.fullscreenToggled()
        }

        // ---- title chip + source badge
        Rectangle {
            visible: root.hasVideo
            x: 12; y: 12
            width: Math.min(root.width * 0.56, titleCol.implicitWidth + 28)
            height: titleCol.implicitHeight + 20
            radius: 12
            color: "#a6101216"
            opacity: root.showChrome ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 220 } }
            Column {
                id: titleCol
                x: 14; y: 10
                width: parent.width - 28
                spacing: 2
                Text {
                    width: parent.width
                    text: backend.title
                    elide: Text.ElideRight
                    color: "#ffffff"
                    font.family: Theme.fontUi; font.pixelSize: 13; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    text: backend.channel
                    elide: Text.ElideRight
                    color: "#c4c9cf"
                    font.family: Theme.fontUi; font.pixelSize: 12
                }
            }
        }
        Rectangle {
            visible: root.hasVideo
            anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 12
            width: badge.implicitWidth + 20; height: 26; radius: 13
            color: "#a6101216"
            opacity: root.showChrome ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 220 } }
            Text {
                id: badge
                anchors.centerIn: parent
                text: backend.sourceBadge
                color: "#e8ecef"
                font.family: Theme.fontMono; font.pixelSize: 12
            }
        }

        // ---- big play button
        Rectangle {
            id: bigPlay
            anchors.centerIn: parent
            width: 72; height: 72; radius: 36
            color: "#59ffffff"
            visible: root.hasVideo && backend.hasPreview
            opacity: backend.playing ? 0 : 1
            scale: backend.playing ? 1.25 : (bpMa.containsMouse ? 1.08 : 1.0)
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Behavior on scale { SpringAnimation { spring: 4; damping: 0.35; epsilon: 0.002 } }
            Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 3; d: Icons.play; size: 28; color: "#ffffff"; filled: true; strokeWidth: 0 }
            MouseArea { id: bpMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.togglePlay() }
        }

        // ---- control bar
        Rectangle {
            id: bar
            visible: root.hasVideo
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 }
            height: 48
            radius: 14
            color: "#b3101216"
            opacity: root.showChrome ? 1 : 0
            transform: Translate { y: root.showChrome ? 0 : 8; Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } } }
            Behavior on opacity { NumberAnimation { duration: 220 } }

            RowLayout {
                anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                spacing: 4

                component CtlBtn: Rectangle {
                    id: cb
                    property string icon: ""
                    property bool on: false
                    property bool filled: false
                    property string tip: ""
                    signal clicked()
                    Layout.preferredWidth: 34; Layout.preferredHeight: 34
                    radius: 9
                    color: cma.containsMouse ? "#26ffffff" : "transparent"
                    scale: cma.pressed ? 0.9 : 1
                    Behavior on scale { SpringAnimation { spring: 6; damping: 0.4; epsilon: 0.002 } }
                    Icon { anchors.centerIn: parent; d: cb.icon; size: 16; color: cb.on ? Theme.acc : "#ffffff"; filled: cb.filled; strokeWidth: cb.filled ? 0 : 2 }
                    MouseArea { id: cma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: cb.clicked() }
                    Accessible.role: Accessible.Button
                    Accessible.name: tip
                }

                CtlBtn { icon: Icons.skipBack; tip: "Back 5 seconds"; onClicked: backend.step(-5) }
                CtlBtn { icon: backend.playing ? Icons.pause : Icons.play; filled: true; tip: backend.playing ? "Pause" : "Play"; onClicked: backend.togglePlay() }
                CtlBtn { icon: Icons.skipFwd; tip: "Forward 5 seconds"; onClicked: backend.step(5) }
                Text {
                    text: backend.fmt(backend.positionSec)
                    color: "#ffffff"
                    font.family: Theme.fontMono; font.pixelSize: 12
                    Layout.preferredWidth: 46
                    horizontalAlignment: Text.AlignRight
                }

                Item {  // scrub bar with the clip region marked
                    id: scrub
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    readonly property real frac: backend.duration > 0 ? backend.positionSec / backend.duration : 0
                    Rectangle { id: sg; anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: scrubArea.pressed ? 7 : 5; radius: 3.5; color: "#40ffffff"
                        Behavior on height { NumberAnimation { duration: 120 } } }
                    Rectangle {  // clip region
                        anchors.verticalCenter: parent.verticalCenter
                        x: backend.duration > 0 ? backend.startSec / backend.duration * parent.width : 0
                        width: backend.duration > 0 ? (backend.endSec - backend.startSec) / backend.duration * parent.width : 0
                        height: sg.height; radius: 3.5
                        color: Theme.alpha(Theme.acc, 0.55)
                    }
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width * scrub.frac; height: sg.height; radius: 3.5; color: "#ffffff" }
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        x: parent.width * scrub.frac - width / 2
                        width: scrubArea.pressed || scrubArea.containsMouse ? 14 : 0; height: width; radius: width / 2; color: "#ffffff"
                        Behavior on width { SpringAnimation { spring: 6; damping: 0.4; epsilon: 0.2 } }
                    }
                    MouseArea {
                        id: scrubArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onPressed: (m) => { backend.setScrubbing(true); backend.seek(m.x / width * backend.duration) }
                        onPositionChanged: (m) => { if (pressed) backend.seek(Math.max(0, Math.min(1, m.x / width)) * backend.duration) }
                        onReleased: backend.setScrubbing(false)
                    }
                }
                Text {
                    text: backend.fmt(backend.duration)
                    color: "#c4c9cf"
                    font.family: Theme.fontMono; font.pixelSize: 12
                    Layout.preferredWidth: 46
                }
                CtlBtn { icon: Icons.loop; on: backend.loopClip; tip: "Loop clip (L)"; onClicked: backend.toggleLoop() }
                CtlBtn { icon: (backend.muted || backend.volume <= 0) ? Icons.volumeX : Icons.volume; tip: "Mute"; onClicked: backend.toggleMute() }
                CtlBtn { icon: root.fullscreenMode ? Icons.collapse : Icons.expand; tip: "Full screen (F)"; onClicked: root.fullscreenToggled() }
            }
        }

    }
    Item {
        id: maskShape
        anchors.fill: parent
        visible: false
        layer.enabled: GraphicsInfo.api !== GraphicsInfo.Software
        Rectangle { anchors.fill: parent; radius: root.radius; color: "black" }
    }
}
