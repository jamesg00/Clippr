import QtQuick
import QtQuick.Layouts

// Right-hand panel. Shows Output settings while idle, then crossfades to Progress, Done or Error.
Card {
    id: root

    readonly property string st: backend.state
    property string tab: "output"
    readonly property string mode: st === "downloading" ? "progress" : st === "done" ? "done" : st === "error" ? "error" : "settings"

    component Label: Text {
        color: Theme.t3
        font.family: Theme.fontUi
        font.pixelSize: 11
        font.weight: Font.DemiBold
        font.letterSpacing: 0.6
        font.capitalization: Font.AllUppercase
    }

    // each page fades and slides in/out
    component Page: Item {
        property bool shown: false
        anchors.fill: parent
        opacity: shown ? 1 : 0
        visible: opacity > 0.01
        transform: Translate { y: shown ? 0 : 10; Behavior on y { NumberAnimation { duration: Theme.springMs; easing.type: Easing.OutCubic } } }
        Behavior on opacity { NumberAnimation { duration: Theme.springMs; easing.type: Easing.OutCubic } }
    }

    // ============================================================ settings
    Page {
        shown: root.mode === "settings"
        enabled: shown
        anchors.margins: 16

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            Seg {
                Layout.fillWidth: true
                implicitHeight: 36
                model: [{ value: "file", label: "File" }, { value: "output", label: "Output" }]
                current: root.tab
                onPicked: (v) => root.tab = v
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                // ---- File tab
                ColumnLayout {
                    anchors.fill: parent
                    anchors.topMargin: 14
                    spacing: 6
                    opacity: root.tab === "file" ? 1 : 0
                    visible: opacity > 0.01
                    Behavior on opacity { NumberAnimation { duration: 180 } }
                    Label { text: "File name" }
                    FieldBox {
                        id: nameField
                        Layout.fillWidth: true
                        suffix: "." + backend.extension
                        placeholder: "File name"
                        text: backend.fileName
                        onEdited: (t) => backend.setFileName(t)
                    }
                    Item { height: 6 }
                    Label { text: "Save to" }
                    RowLayout {
                        spacing: 8
                        FieldBox { Layout.fillWidth: true; mono: true; iconPath: Icons.folder; readOnly: true; text: backend.folder }
                        Btn { text: "Browse"; onClicked: backend.browse() }
                    }
                    Item { height: 6 }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: backend.isVideoFormat
                        ColumnLayout {
                            spacing: 2
                            Text { text: "Frame-accurate cut"; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 13; font.weight: Font.Medium }
                            Text { text: backend.precise ? "Re-encodes so the cut lands exactly" : "Fast: cuts on the nearest keyframe"; color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 12 }
                        }
                        Item { Layout.fillWidth: true }
                        AppSwitch { checked: backend.precise; label: "Frame-accurate cut"; onToggled: (v) => backend.setPrecise(v) }
                    }
                    Item { Layout.fillHeight: true }
                }

                // ---- Output tab
                Flickable {
                    anchors.fill: parent
                    anchors.topMargin: 12
                    contentHeight: outCol.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    opacity: root.tab === "output" ? 1 : 0
                    visible: opacity > 0.01
                    Behavior on opacity { NumberAnimation { duration: 180 } }
                ColumnLayout {
                    id: outCol
                    width: parent.width
                    spacing: 5

                    Label { text: "Format" }
                    Seg { Layout.fillWidth: true; model: backend.formatChoices; current: backend.fmtValue; onPicked: (v) => backend.setOutput("format", v) }
                    Item { height: 4 }
                    Label { text: "Size preset"; visible: backend.isVideoFormat }
                    Row {
                        id: presets
                        Layout.fillWidth: true
                        visible: backend.isVideoFormat
                        spacing: 6
                        readonly property var items: [
                            { v: "src",  label: "Original", w: 30, h: 20 },
                            { v: "9:16", label: "9:16",     w: 17, h: 30 },
                            { v: "1:1",  label: "1:1",      w: 26, h: 26 },
                            { v: "4:5",  label: "4:5",      w: 24, h: 30 },
                            { v: "16:9", label: "16:9",     w: 34, h: 19 }
                        ]
                        Repeater {
                            model: presets.items
                            delegate: Rectangle {
                                id: pc
                                required property var modelData
                                readonly property bool on: backend.aspectValue === modelData.v
                                width: (presets.width - presets.spacing * 4) / 5
                                height: 68
                                radius: 12
                                color: on ? Theme.accSoft : Theme.card2A
                                border.width: on ? 2 : 1
                                border.color: on ? Theme.acc : Theme.line
                                scale: pma.pressed ? 0.95 : (pma.containsMouse ? 1.03 : 1)
                                Behavior on scale { SpringAnimation { spring: 5; damping: 0.4; epsilon: 0.002 } }
                                Behavior on color { ColorAnimation { duration: 200 } }
                                Behavior on border.color { ColorAnimation { duration: 200 } }
                                Item {  // the shape of the picture you get
                                    x: (parent.width - 36) / 2; y: 8; width: 36; height: 32
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: pc.modelData.w; height: pc.modelData.h
                                        radius: 4
                                        color: pc.on ? Theme.acc : (pc.modelData.v === "src" ? "transparent" : Theme.alpha(Theme.t3, 0.55))
                                        border.width: pc.modelData.v === "src" ? 1.5 : 0
                                        border.color: pc.on ? Theme.acc : Theme.t3
                                        Behavior on color { ColorAnimation { duration: 200 } }
                                        Icon { visible: pc.modelData.v === "src"; anchors.centerIn: parent; d: Icons.expand; size: 12; color: pc.on ? Theme.acc : Theme.t3 }
                                    }
                                }
                                Text {
                                    anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 8 }
                                    text: pc.modelData.label
                                    color: pc.on ? Theme.acc : Theme.t2
                                    font.family: Theme.fontMono; font.pixelSize: pc.modelData.v === "src" ? 10 : 11; font.weight: Font.DemiBold
                                }
                                MouseArea { id: pma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setOutput("aspect", pc.modelData.v) }
                                Accessible.role: Accessible.RadioButton
                                Accessible.name: modelData.v === "src" ? "Original shape" : "Shape " + modelData.v
                                Accessible.checked: on
                            }
                        }
                    }
                    Text {
                        visible: backend.isVideoFormat
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: Theme.t3
                        font.family: Theme.fontUi; font.pixelSize: 12
                        text: ({ "src": "Keeps the video's own shape.",
                                 "9:16": "Instagram Reels, TikTok and YouTube Shorts. Up to 1080×1920. Drag the box on the video to choose the part you keep.",
                                 "1:1": "Instagram and Facebook square posts. Up to 1080×1080. Drag the box on the video to choose the part you keep.",
                                 "4:5": "Instagram feed portrait posts. Up to 1080×1350. Drag the box on the video to choose the part you keep.",
                                 "16:9": "YouTube and regular widescreen video. Drag the box on the video to choose the part you keep." })[backend.aspectValue] || ""
                    }
                    Item { height: 4; visible: backend.isVideoFormat }
                    Label { text: "Resolution"; visible: backend.isVideoFormat }
                    Seg { Layout.fillWidth: true; visible: backend.isVideoFormat; model: backend.resolutionChoices; current: backend.resValue; onPicked: (v) => backend.setOutput("resolution", v) }
                    Item { height: 4; visible: backend.isVideoFormat }
                    Label { text: "Frame rate"; visible: backend.isVideoFormat }
                    Seg { Layout.fillWidth: true; visible: backend.isVideoFormat; model: backend.fpsChoices; current: backend.fpsValue; onPicked: (v) => backend.setOutput("fps", v) }
                    Item { height: 4; visible: backend.isVideoFormat && !backend.isGif }
                    Label { text: "Codec"; visible: backend.isVideoFormat && !backend.isGif }
                    Seg { Layout.fillWidth: true; visible: backend.isVideoFormat && !backend.isGif; model: backend.codecChoices; current: backend.codecValue; onPicked: (v) => backend.setOutput("codec", v) }
                    Item { height: 4; visible: backend.isVideoFormat }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: backend.isVideoFormat
                        Label { text: "Quality" }
                        Item { Layout.fillWidth: true }
                        Text { text: backend.quality + "%"; color: Theme.t2; font.family: Theme.fontMono; font.pixelSize: 12 }
                    }
                    AppSlider { Layout.fillWidth: true; visible: backend.isVideoFormat; from: 10; to: 100; step: 5; value: backend.quality; label: "Quality"; onMoved: (v) => backend.setQuality(v) }
                    Item { height: 2 }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: backend.isVideoFormat && !backend.isGif
                        Text { text: "Audio"; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 13; font.weight: Font.Medium }
                        Item { Layout.fillWidth: true }
                        AppSwitch { scale: 0.85; checked: backend.audioOn; label: "Audio"; onToggled: (v) => backend.setAudioOn(v) }
                    }
                    Label { text: "Audio bitrate"; visible: !backend.isGif && (backend.audioOn || !backend.isVideoFormat) }
                    Seg { Layout.fillWidth: true; visible: !backend.isGif && (backend.audioOn || !backend.isVideoFormat); model: backend.bitrateChoices; current: String(backend.audioBitrate); onPicked: (v) => backend.setOutput("audioBitrate", v) }
                    Label { text: "Audio language"; visible: backend.audioTracks.length > 1 }
                    Seg { Layout.fillWidth: true; visible: backend.audioTracks.length > 1; model: backend.audioTracks; current: backend.audioLang; onPicked: (v) => backend.setAudioTrack(v) }
                }
                }
            }

            // estimate + download, always visible on the settings page
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 40
                radius: 12
                color: Theme.card2A
                visible: backend.estimateText !== ""
                RowLayout {
                    anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                    Text { text: backend.estimateText; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 13; Layout.fillWidth: true }
                    Rectangle {
                        implicitWidth: tagText.implicitWidth + 18; implicitHeight: 22; radius: 11
                        color: Theme.accSoft
                        visible: backend.encodeTag !== ""
                        Text { id: tagText; anchors.centerIn: parent; text: backend.encodeTag; color: Theme.acc; font.family: Theme.fontUi; font.pixelSize: 11; font.weight: Font.DemiBold }
                    }
                }
            }
            Item { implicitHeight: 12 }
            Rectangle {
                id: cta
                Layout.fillWidth: true
                implicitHeight: 48
                radius: 14
                color: Theme.acc
                opacity: backend.canDownload ? 1 : 0.4
                scale: ctaMa.pressed ? 0.98 : (ctaMa.containsMouse && backend.canDownload ? 1.01 : 1)
                Behavior on scale { SpringAnimation { spring: 4; damping: 0.35; epsilon: 0.002 } }
                Behavior on opacity { NumberAnimation { duration: 180 } }
                Row {
                    anchors.centerIn: parent
                    spacing: 8
                    Icon { d: Icons.download; size: 18; color: Theme.accText; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "Download clip"; color: Theme.accText; font.family: Theme.fontUi; font.pixelSize: 14; font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
                }
                MouseArea { id: ctaMa; anchors.fill: parent; hoverEnabled: true; enabled: backend.canDownload; cursorShape: Qt.PointingHandCursor; onClicked: backend.download() }
                Accessible.role: Accessible.Button
                Accessible.name: "Download clip"
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 8
                horizontalAlignment: Text.AlignHCenter
                text: backend.summaryText
                color: Theme.t3
                font.family: Theme.fontMono; font.pixelSize: 11
            }
        }
    }

    // ============================================================ progress
    Page {
        shown: root.mode === "progress"
        enabled: shown
        anchors.margins: 20

        ColumnLayout {
            anchors.fill: parent
            spacing: 6

            Item { Layout.fillHeight: true }
            Item {  // progress ring
                Layout.alignment: Qt.AlignHCenter
                width: 150; height: 150
                Canvas {
                    id: ring
                    anchors.fill: parent
                    property real p: Math.max(0, backend.progress)
                    property real shownP: p
                    Behavior on shownP { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    onShownPChanged: requestPaint()
                    Connections { target: Theme; function onAccChanged() { ring.requestPaint() } }
                    onPaint: {
                        const c = getContext("2d"); c.reset()
                        c.lineWidth = 10; c.lineCap = "round"
                        c.strokeStyle = Theme.card2
                        c.beginPath(); c.arc(75, 75, 66, 0, Math.PI * 2); c.stroke()
                        c.strokeStyle = Theme.acc
                        c.beginPath(); c.arc(75, 75, 66, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0.001, shownP)); c.stroke()
                    }
                    RotationAnimator on rotation { running: backend.progress < 0; from: 0; to: 360; duration: 1100; loops: Animation.Infinite }
                    onVisibleChanged: if (!visible) rotation = 0
                }
                Text {
                    anchors.centerIn: parent
                    text: backend.progress < 0 ? "…" : Math.round(backend.progress * 100) + "%"
                    color: Theme.text
                    font.family: Theme.fontUi; font.pixelSize: 34; font.weight: Font.Bold
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 12
                horizontalAlignment: Text.AlignHCenter
                text: backend.jobPhase
                color: Theme.acc
                font.family: Theme.fontUi; font.pixelSize: 14; font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: backend.jobTitle
                elide: Text.ElideMiddle
                color: Theme.text
                font.family: Theme.fontUi; font.pixelSize: 13
            }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: backend.jobSub
                wrapMode: Text.WordWrap
                color: Theme.t3
                font.family: Theme.fontMono; font.pixelSize: 11
            }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: backend.jobDetail
                color: Theme.t2
                font.family: Theme.fontMono; font.pixelSize: 12
            }
            Item { Layout.fillHeight: true }
            Btn { Layout.fillWidth: true; text: "Cancel"; danger: true; onClicked: backend.cancel() }
        }
    }

    // ============================================================ done
    Page {
        id: donePage
        shown: root.mode === "done"
        enabled: shown
        anchors.margins: 20

        ColumnLayout {
            anchors.fill: parent
            spacing: 8
            Item { Layout.fillHeight: true }
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 84; height: 84; radius: 42
                color: Theme.accSoft
                scale: donePage.shown ? 1 : 0.4
                Behavior on scale { SpringAnimation { spring: 3.2; damping: 0.28; epsilon: 0.002 } }
                Icon { anchors.centerIn: parent; d: Icons.check; size: 40; strokeWidth: 3; color: Theme.acc }
            }
            Text { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 10; text: "Clip saved"; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 20; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: backend.resultName; elide: Text.ElideMiddle; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 13 }
            Text { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: backend.resultMeta; wrapMode: Text.WordWrap; color: Theme.t2; font.family: Theme.fontMono; font.pixelSize: 12 }
            Text { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: backend.resultElapsed; color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 12 }
            Item { Layout.fillHeight: true }
            Btn { Layout.fillWidth: true; text: "Show in folder"; primary: true; iconPath: Icons.folder; onClicked: backend.showInFolder() }
            Btn { Layout.fillWidth: true; text: "Make another clip"; onClicked: backend.backToReady() }
        }
    }

    // ============================================================ error
    Page {
        shown: root.mode === "error"
        enabled: shown
        anchors.margins: 20

        ColumnLayout {
            anchors.fill: parent
            spacing: 8
            Item { Layout.fillHeight: true }
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 72; height: 72; radius: 36
                color: Theme.alpha(Theme.danger, 0.16)
                Icon { anchors.centerIn: parent; d: Icons.alert; size: 32; color: Theme.danger }
            }
            Text { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 8; text: backend.errorTitle; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 18; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: backend.errorMessage; wrapMode: Text.WordWrap; color: Theme.t2; font.family: Theme.fontUi; font.pixelSize: 13 }
            Item { Layout.fillHeight: true }
            Btn { Layout.fillWidth: true; text: "Try again"; primary: true; onClicked: backend.retry() }
            Btn { Layout.fillWidth: true; text: "Back"; onClicked: backend.backToReady() }
        }
    }
}
