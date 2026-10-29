import QtQuick

// iOS-style switch. The knob springs and stretches slightly while pressed.
Rectangle {
    id: root
    property bool checked: false
    property string label: ""
    signal toggled(bool value)

    width: 48
    height: 29
    radius: height / 2
    color: checked ? Theme.acc : Theme.card2
    Behavior on color { ColorAnimation { duration: 220 } }

    Rectangle {
        id: knob
        y: 2
        height: 25
        width: ma.pressed ? 29 : 25
        radius: 12.5
        color: "#ffffff"
        x: root.checked ? root.width - width - 2 : 2
        Behavior on x { SpringAnimation { spring: 5; damping: 0.4; epsilon: 0.25 } }
        Behavior on width { NumberAnimation { duration: 120 } }
        layer.enabled: true
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.checked: checked
    Accessible.onToggleAction: toggled(!checked)
    activeFocusOnTab: true
    Keys.onSpacePressed: toggled(!checked)
    Rectangle {
        anchors.fill: parent
        anchors.margins: -3
        radius: height / 2
        color: "transparent"
        border.width: 2
        border.color: Theme.acc
        visible: root.activeFocus
    }
}
