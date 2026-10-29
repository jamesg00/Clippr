import QtQuick
import QtQuick.Layouts

// Translucent source-list sidebar with the five sessions. The selection pill slides between rows with a spring.
Rectangle {
    id: root
    color: Theme.side
    property var window: null
    signal closeRequested()

    readonly property var items: [
        { id: "clip",     label: "Clip Video", key: "Ctrl+1", icon: Icons.scissors },
        { id: "mp3",      label: "To MP3",     key: "Ctrl+2", icon: Icons.music },
        { id: "convert",  label: "Convert",    key: "Ctrl+3", icon: Icons.convert },
        { id: "resize",   label: "Resize",     key: "Ctrl+4", icon: Icons.resize },
        { id: "compress", label: "Compress",   key: "Ctrl+5", icon: Icons.compress }
    ]
    readonly property bool maximized: window && window.visibility === Window.Maximized

    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }

    // drag the window by the empty top area
    MouseArea {
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 80
        onPressed: if (root.window) root.window.startSystemMove()
        onDoubleClicked: if (root.window) root.window.visibility = root.maximized ? Window.Windowed : Window.Maximized
    }

    // brand
    Row {
        x: 18; y: 22
        spacing: 10
        Rectangle {
            width: 28; height: 28; radius: 9
            color: Theme.acc
            Icon { anchors.centerIn: parent; d: Icons.scissors; size: 15; strokeWidth: 2.6; color: Theme.accText }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Clippr"
            color: Theme.text
            font.family: Theme.fontUi; font.pixelSize: 17; font.weight: Font.Bold
        }
    }

    Text {
        x: 22; y: 72
        text: "SESSIONS"
        color: Theme.t3
        font.family: Theme.fontUi; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.8
    }

    // selection pill
    Rectangle {
        id: pill
        readonly property int idx: {
            if (backend.session === "appearance") return 5
            for (let i = 0; i < root.items.length; i++) if (root.items[i].id === backend.session) return i
            return 0
        }
        x: 10
        width: root.width - 20
        height: 38
        radius: 10
        color: Theme.accSoft
        y: idx === 5 ? appearanceBtn.y : 96 + idx * 40
        Behavior on y { SpringAnimation { spring: Theme.reduceMotion ? 12 : 5; damping: Theme.reduceMotion ? 1 : 0.36; epsilon: 0.25 } }
    }

    Column {
        x: 10; y: 96
        width: root.width - 20
        spacing: 2
        Repeater {
            model: root.items
            delegate: Item {
                id: row
                required property var modelData
                width: parent.width; height: 38
                readonly property bool on: backend.session === modelData.id
                scale: rma.pressed ? 0.97 : 1
                Behavior on scale { SpringAnimation { spring: 6; damping: 0.4; epsilon: 0.002 } }
                Rectangle {
                    anchors.fill: parent; radius: 10
                    color: Theme.text; opacity: rma.containsMouse && !row.on ? 0.06 : 0
                    Behavior on opacity { NumberAnimation { duration: 130 } }
                }
                Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; d: row.modelData.icon; size: 17; color: row.on ? Theme.acc : Theme.t2 }
                Text {
                    x: 40; anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.label
                    color: row.on ? Theme.acc : Theme.t2
                    font.family: Theme.fontUi; font.pixelSize: 14; font.weight: Font.Medium
                    Behavior on color { ColorAnimation { duration: 200 } }
                }
                MouseArea { id: rma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setSession(row.modelData.id) }
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
            }
        }
    }

    // bottom: appearance + tool status
    Item {
        id: appearanceBtn
        x: 10
        y: root.height - 56
        width: root.width - 20; height: 38
        readonly property bool on: backend.session === "appearance"
        scale: apma.pressed ? 0.97 : 1
        Behavior on scale { SpringAnimation { spring: 6; damping: 0.4; epsilon: 0.002 } }
        Rectangle {
            anchors.fill: parent; radius: 10
            color: Theme.text; opacity: apma.containsMouse && !appearanceBtn.on ? 0.06 : 0
            Behavior on opacity { NumberAnimation { duration: 130 } }
        }
        Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; d: Icons.palette; size: 17; color: appearanceBtn.on ? Theme.acc : Theme.t2 }
        Text {
            x: 40; anchors.verticalCenter: parent.verticalCenter
            text: "Appearance"
            color: appearanceBtn.on ? Theme.acc : Theme.t2
            font.family: Theme.fontUi; font.pixelSize: 14; font.weight: Font.Medium
            Behavior on color { ColorAnimation { duration: 200 } }
        }
        MouseArea { id: apma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setSession("appearance") }
        Accessible.role: Accessible.Button
        Accessible.name: "Appearance"
    }
}
