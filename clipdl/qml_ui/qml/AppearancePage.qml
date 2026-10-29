import QtQuick
import QtQuick.Layouts

// Theme gallery + window material, frost blur, window opacity and reduce-motion.
Item {
    id: root

    readonly property var themes: [
        { id: "auto",     label: "Match system", bg: "#f5f5f7", bg2: "#1c1c1e", acc: "#0a84ff", chip: "#8a8a90" },
        { id: "light",    label: "Light",    bg: "#f5f5f7", acc: "#0066d6", chip: "#d6d6dc" },
        { id: "graphite", label: "Dark",     bg: "#1c1c1e", acc: "#0a84ff", chip: "#38383c" },
        { id: "noir",     label: "Noir",     bg: "#000000", acc: "#ffffff", chip: "#2a2a2a" },
        { id: "paper",    label: "Paper",    bg: "#ffffff", acc: "#000000", chip: "#d4d4d4" },
        { id: "mint",     label: "Mint",     bg: "#07150f", acc: "#2ee59d", chip: "#14231b" },
        { id: "midnight", label: "Midnight", bg: "#12102a", acc: "#b794ff", chip: "#292552" },
        { id: "ocean",    label: "Ocean",    bg: "#08141f", acc: "#4fd1ff", chip: "#17344d" },
        { id: "sunset",   label: "Sunset",   bg: "#1f1311", acc: "#ff9f6b", chip: "#3c2620" },
        { id: "rose",     label: "Rose",     bg: "#1f1218", acc: "#ff7eb6", chip: "#3d2231" }
    ]
    readonly property bool solid: backend.mode === "solid"

    component Row2: RowLayout {
        property string title: ""
        property string sub: ""
        default property alias content: slot.data
        Layout.fillWidth: true
        spacing: 16
        ColumnLayout {
            spacing: 2
            Layout.fillWidth: true
            Text { text: parent.parent.title; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 14; font.weight: Font.DemiBold }
            Text { text: parent.parent.sub; color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        RowLayout { id: slot; spacing: 10 }
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            x: 20
            y: 34
            width: parent.width - 40
            spacing: 20

            ColumnLayout {
                spacing: 4
                Text { text: "Appearance"; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 28; font.weight: Font.Bold }
                Text { text: "Ten looks, including Noir (pure black and white) and Paper. The whole window re-themes live."; color: Theme.t2; font.family: Theme.fontUi; font.pixelSize: 14 }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 5
                rowSpacing: 10
                columnSpacing: 10
                Repeater {
                    model: root.themes
                    delegate: Rectangle {
                        id: tc
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.preferredHeight: 104
                        radius: 16
                        color: Theme.cardA
                        border.width: backend.themeId === modelData.id ? 2 : 1
                        border.color: backend.themeId === modelData.id ? Theme.acc : Theme.line
                        scale: tma.pressed ? 0.97 : (tma.containsMouse ? 1.025 : 1)
                        Behavior on scale { SpringAnimation { spring: 5; damping: 0.38; epsilon: 0.002 } }
                        Behavior on border.color { ColorAnimation { duration: 200 } }

                        Rectangle {
                            x: 8; y: 8; width: parent.width - 16; height: 58; radius: 10
                            color: tc.modelData.bg
                            Rectangle {  // "auto" shows the light/dark split
                                visible: tc.modelData.bg2 !== undefined
                                anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
                                width: parent.width / 2; radius: 10
                                color: tc.modelData.bg2 !== undefined ? tc.modelData.bg2 : "transparent"
                            }
                            Row {
                                anchors.left: parent.left; anchors.bottom: parent.bottom
                                anchors.margins: 8
                                spacing: 5
                                Rectangle { width: 30; height: 16; radius: 5; color: tc.modelData.acc }
                                Rectangle { width: 18; height: 16; radius: 5; color: tc.modelData.chip }
                            }
                        }
                        Text {
                            anchors { left: parent.left; bottom: parent.bottom; margins: 12 }
                            text: tc.modelData.label
                            color: Theme.text
                            font.family: Theme.fontUi; font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                        Icon {
                            visible: backend.themeId === tc.modelData.id
                            anchors { right: parent.right; bottom: parent.bottom; margins: 11 }
                            d: Icons.check; size: 14; strokeWidth: 3; color: Theme.acc
                        }
                        MouseArea { id: tma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setTheme(tc.modelData.id) }
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label
                        Accessible.checked: backend.themeId === modelData.id
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                implicitHeight: settingsCol.implicitHeight + 16
                ColumnLayout {
                    id: settingsCol
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16; topMargin: 8 }
                    spacing: 0

                    Row2 {
                        title: "Window material"
                        sub: "Solid is an ordinary window. Glass lets your desktop show through."
                        Seg {
                            implicitWidth: 200
                            model: [{ value: "solid", label: "Solid" }, { value: "glass", label: "Glass" }]
                            current: backend.mode
                            onPicked: (v) => backend.setMode(v)
                        }
                        Layout.topMargin: 8; Layout.bottomMargin: 8
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                    Row2 {
                        title: "Frost"
                        sub: "0 is perfectly clear. Higher blurs your desktop behind the window more."
                        opacity: root.solid ? 0.45 : 1
                        AppSlider { implicitWidth: 230; from: 0; to: 100; step: 5; value: backend.frost; isEnabled: !root.solid; label: "Frost"; onMoved: (v) => backend.setFrost(Math.round(v)) }
                        Rectangle { implicitWidth: 56; implicitHeight: 24; radius: 12; color: Theme.accSoft
                            Text { anchors.centerIn: parent; text: backend.frost + "%"; color: Theme.acc; font.family: Theme.fontMono; font.pixelSize: 12; font.weight: Font.DemiBold } }
                        Layout.topMargin: 10; Layout.bottomMargin: 10
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                    Row2 {
                        title: "Window opacity"
                        sub: "Thins the window and its panels together. Go low (with Frost at 0) to see straight through to your screen."
                        opacity: root.solid ? 0.45 : 1
                        AppSlider { implicitWidth: 230; from: 0.15; to: 1.0; step: 0.05; value: backend.opacity; isEnabled: !root.solid; label: "Window opacity"; onMoved: (v) => backend.setOpacity(v) }
                        Rectangle { implicitWidth: 56; implicitHeight: 24; radius: 12; color: Theme.accSoft
                            Text { anchors.centerIn: parent; text: Math.round(backend.opacity * 100) + "%"; color: Theme.acc; font.family: Theme.fontMono; font.pixelSize: 12; font.weight: Font.DemiBold } }
                        Layout.topMargin: 10; Layout.bottomMargin: 10
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                    Row2 {
                        title: "Reduce motion"
                        sub: "Swaps springs for quick fades. Theme color changes still blend, just faster."
                        AppSwitch { checked: backend.reduceMotion; label: "Reduce motion"; onToggled: (v) => backend.setReduceMotion(v) }
                        Layout.topMargin: 10; Layout.bottomMargin: 8
                    }
                }
            }
        }
    }
}
