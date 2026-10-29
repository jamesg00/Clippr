import QtQuick

// Minimize / maximize / close, top right, Windows style.
Row {
    id: root
    property var window: null
    signal closeRequested()
    readonly property bool maximized: window && window.visibility === Window.Maximized

    component CtlButton: Rectangle {
        id: b
        property string kind: "min"
        signal clicked()
        width: 46; height: 30
        color: kind === "close" ? (ma.containsMouse ? "#e81123" : "transparent")
                                : (ma.containsMouse ? Theme.alpha(Theme.text, ma.pressed ? 0.16 : 0.09) : "transparent")
        Behavior on color { ColorAnimation { duration: 110 } }
        property color ink: kind === "close" && ma.containsMouse ? "#ffffff" : Theme.t2
        Behavior on ink { ColorAnimation { duration: 110 } }

        Rectangle { visible: b.kind === "min"; anchors.centerIn: parent; width: 10; height: 1; color: b.ink }
        Item {
            visible: b.kind === "max"
            anchors.centerIn: parent
            width: 10; height: 10
            Rectangle {  // restore: the back square
                visible: root.maximized
                x: 2; y: 0; width: 8; height: 8; color: "transparent"; border.width: 1; border.color: b.ink
            }
            Rectangle {
                x: 0; y: root.maximized ? 2 : 0; width: root.maximized ? 8 : 10; height: root.maximized ? 8 : 10
                color: root.maximized ? Theme.winS : "transparent"; border.width: 1; border.color: b.ink
            }
        }
        Item {
            visible: b.kind === "close"
            anchors.centerIn: parent
            width: 12; height: 12
            Rectangle { anchors.centerIn: parent; width: 15; height: 1.2; rotation: 45; color: b.ink }
            Rectangle { anchors.centerIn: parent; width: 15; height: 1.2; rotation: -45; color: b.ink }
        }
        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: b.clicked() }
        Accessible.role: Accessible.Button
        Accessible.name: kind === "min" ? "Minimize" : kind === "max" ? (root.maximized ? "Restore" : "Maximize") : "Close"
    }

    CtlButton { kind: "min"; onClicked: if (root.window) root.window.showMinimized() }
    CtlButton {
        kind: "max"
        onClicked: if (root.window) root.window.visibility = root.maximized ? Window.Windowed : Window.Maximized
    }
    CtlButton { kind: "close"; onClicked: root.closeRequested() }
}
