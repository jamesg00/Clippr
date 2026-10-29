import QtQuick
import QtQuick.Layouts

// Clip Video session: link bar on top, player + trim on the left, inspector on the right.
Item {
    id: root
    property bool fullscreenPreview: false
    signal fullscreenToggled()

    readonly property bool hasVideo: backend.state === "ready" || backend.state === "done"
                                     || backend.state === "downloading" || backend.state === "error"
    readonly property alias urlField: urlBox.input

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: root.fullscreenPreview ? 0 : 20
        anchors.rightMargin: root.fullscreenPreview ? 0 : 20
        anchors.bottomMargin: root.fullscreenPreview ? 0 : 14
        spacing: 0

        // ---- link bar
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 16
            Layout.bottomMargin: 12
            spacing: 10
            visible: !root.fullscreenPreview
            FieldBox {
                id: urlBox
                Layout.fillWidth: true
                iconPath: Icons.link
                placeholder: "Paste a link, or drop a video file here"
                text: backend.urlText
                onEdited: (t) => backend.setUrlText(t)
                onAccepted: (t) => backend.loadUrl(t)
                border.color: backend.urlError !== "" ? Theme.danger : (input.activeFocus ? Theme.acc : Theme.line)
            }
            Btn { text: "Open file"; onClicked: backend.browseFile(); isEnabled: backend.state !== "downloading" && backend.state !== "loading" }
            Btn { text: "Paste"; onClicked: backend.pasteAndLoad(); isEnabled: backend.state !== "downloading" }
            Btn { text: backend.state === "loading" ? "Loading…" : "Load"; primary: true; isEnabled: backend.state !== "downloading" && backend.state !== "loading" && urlBox.text.length > 0; onClicked: backend.loadUrl(urlBox.text) }
            Btn { visible: root.hasVideo && backend.state !== "downloading"; text: "Clear"; onClicked: backend.clear() }
        }
        Text {
            visible: backend.urlError !== "" && !root.fullscreenPreview
            Layout.bottomMargin: 8
            text: backend.urlError
            color: Theme.danger
            font.family: Theme.fontUi; font.pixelSize: 13
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14

                PlayerCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 240
                    fullscreenMode: root.fullscreenPreview
                    onFullscreenToggled: root.fullscreenToggled()
                    radius: root.fullscreenPreview ? 0 : Theme.radiusCard
                }

                Card {
                    id: trimCard
                    Layout.fillWidth: true
                    Layout.preferredHeight: 262
                    visible: !root.fullscreenPreview
                    opacity: root.hasVideo ? 1 : 0.45
                    Behavior on opacity { NumberAnimation { duration: 240 } }
                    enabled: root.hasVideo

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 10

                        RowLayout {
                            spacing: 10
                            Text { text: "Trim"; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 15; font.weight: Font.Bold }
                            Text {
                                Layout.fillWidth: true
                                text: backend.state === "downloading" ? "Locked while downloading"
                                      : "Drag the clip to move it, its edges to trim. Click to scrub."
                                color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                            Row {
                                spacing: 4
                                Btn { compact: true; implicitWidth: 30; text: "−"; onClicked: track.zoomBy(0.7); isEnabled: track.zoom > 1.01 }
                                Btn { compact: true; implicitWidth: 30; text: "+"; onClicked: track.zoomBy(1.4); isEnabled: track.zoom < track.maxZoom - 0.01 }
                                Btn { compact: true; text: "Fit"; onClicked: track.fit(); isEnabled: track.zoom > 1.01 }
                            }
                            Rectangle {
                                implicitWidth: pillText.implicitWidth + 22; implicitHeight: 26; radius: 13
                                color: Theme.accSoft
                                Text {
                                    id: pillText
                                    anchors.centerIn: parent
                                    text: "Clip  " + backend.fmtTenths(backend.endSec - backend.startSec)
                                    color: Theme.acc; font.family: Theme.fontMono; font.pixelSize: 12; font.weight: Font.DemiBold
                                }
                            }
                        }

                        TrimTrack { id: track; objectName: "trimTrack"; Layout.fillWidth: true; Layout.preferredHeight: implicitHeight }

                        RowLayout {
                            spacing: 12
                            component TimeField: ColumnLayout {
                                id: tf
                                property string label: ""
                                property real value: 0
                                signal committed(string text)
                                signal nudged(real delta)
                                spacing: 4
                                Text { text: tf.label; color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 11; font.weight: Font.DemiBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 0.6 }
                                RowLayout {
                                    spacing: 6
                                    Btn { compact: true; text: "−"; implicitWidth: 32; onClicked: tf.nudged(-1) }
                                    FieldBox {
                                        id: fld
                                        mono: true
                                        implicitWidth: 104; implicitHeight: 34
                                        text: backend.fmtTenths(tf.value)
                                        onAccepted: (t) => { tf.committed(t); input.focus = false }
                                        Connections { target: backend; function onRangeChanged() { if (!fld.input.activeFocus) fld.text = backend.fmtTenths(tf.value) } }
                                    }
                                    Btn { compact: true; text: "+"; implicitWidth: 32; onClicked: tf.nudged(1) }
                                }
                            }
                            TimeField { label: "Start"; value: backend.startSec; onCommitted: (t) => backend.setStartText(t); onNudged: (d) => backend.nudgeStart(d) }
                            Icon { d: "M5 12h14M13 6l6 6-6 6"; size: 18; color: Theme.t3; Layout.alignment: Qt.AlignBottom; Layout.bottomMargin: 8 }
                            TimeField { label: "End"; value: backend.endSec; onCommitted: (t) => backend.setEndText(t); onNudged: (d) => backend.nudgeEnd(d) }
                            Item { Layout.fillWidth: true }
                            Btn { compact: true; text: "Set start (I)"; Layout.alignment: Qt.AlignBottom; onClicked: backend.markStart() }
                            Btn { compact: true; text: "Set end (O)"; Layout.alignment: Qt.AlignBottom; onClicked: backend.markEnd() }
                        }
                    }
                }
            }

            Inspector {
                Layout.preferredWidth: 340
                Layout.fillHeight: true
                visible: !root.fullscreenPreview
                opacity: root.hasVideo ? 1 : 0.55
                Behavior on opacity { NumberAnimation { duration: 240 } }
                enabled: root.hasVideo
            }
        }
    }
}
