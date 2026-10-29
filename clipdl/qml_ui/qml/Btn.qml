import QtQuick

// Pill / rounded button with a spring press: scales down under the finger, springs back on release.
Rectangle {
    id: root
    property string text: ""
    property bool primary: false
    property bool danger: false
    property string iconPath: ""
    property bool compact: false
    property bool isEnabled: true
    signal clicked()

    implicitHeight: compact ? 32 : 40
    implicitWidth: row.implicitWidth + (compact ? 24 : 32)
    radius: compact ? 9 : Theme.radiusCtl + 1
    color: primary ? Theme.acc : (danger ? Theme.alpha(Theme.danger, 0.16) : Theme.card2A)
    border.width: primary ? 0 : 1
    border.color: Theme.line
    opacity: isEnabled ? 1 : 0.4
    scale: ma.pressed ? 0.96 : (ma.containsMouse ? 1.015 : 1.0)
    Behavior on scale { SpringAnimation { spring: 4; damping: 0.32; epsilon: 0.002 } }
    Behavior on opacity { NumberAnimation { duration: 150 } }

    Rectangle {  // hover sheen
        anchors.fill: parent
        radius: parent.radius
        color: Theme.text
        opacity: ma.containsMouse && root.isEnabled ? (root.primary ? 0.0 : 0.06) : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 8
        Icon {
            visible: root.iconPath !== ""
            d: root.iconPath
            size: 16
            anchors.verticalCenter: parent.verticalCenter
            color: root.primary ? Theme.accText : (root.danger ? Theme.danger : Theme.text)
        }
        Text {
            text: root.text
            anchors.verticalCenter: parent.verticalCenter
            color: root.primary ? Theme.accText : (root.danger ? Theme.danger : Theme.text)
            font.family: Theme.fontUi
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.isEnabled
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: if (isEnabled) clicked()
    activeFocusOnTab: true
    Keys.onReturnPressed: if (isEnabled) clicked()
    Keys.onSpacePressed: if (isEnabled) clicked()
    Rectangle {  // keyboard focus ring
        anchors.fill: parent
        anchors.margins: -3
        radius: parent.radius + 3
        color: "transparent"
        border.width: 2
        border.color: Theme.acc
        visible: root.activeFocus
    }
}
