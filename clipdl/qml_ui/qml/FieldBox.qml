import QtQuick

// A rounded text field. Grows an accent ring while focused.
Rectangle {
    id: root
    property alias text: input.text
    property alias placeholder: ph.text
    property alias input: input
    property bool mono: false
    property string suffix: ""
    property string iconPath: ""
    property bool readOnly: false
    signal accepted(string text)
    signal edited(string text)

    implicitHeight: 40
    radius: Theme.radiusCtl + 1
    color: Theme.card2A
    border.width: input.activeFocus ? 2 : 1
    border.color: input.activeFocus ? Theme.acc : Theme.line
    Behavior on border.color { ColorAnimation { duration: 160 } }

    Rectangle {  // soft focus glow
        anchors.fill: parent
        anchors.margins: -4
        radius: parent.radius + 4
        color: "transparent"
        border.width: 4
        border.color: Theme.accSoft
        opacity: input.activeFocus ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
    }

    Row {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 8
        Icon {
            visible: root.iconPath !== ""
            d: root.iconPath
            size: 16
            color: Theme.t3
            anchors.verticalCenter: parent.verticalCenter
        }
        Item {
            width: parent.width - (root.iconPath !== "" ? 24 : 0) - (suffixText.visible ? suffixText.width + 8 : 0)
            height: parent.height
            Text {
                id: ph
                anchors.verticalCenter: parent.verticalCenter
                visible: input.text.length === 0
                color: Theme.t3
                font.family: Theme.fontUi
                font.pixelSize: 14
            }
            TextInput {
                id: input
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                color: Theme.text
                selectionColor: Theme.acc
                selectedTextColor: Theme.accText
                font.family: root.mono ? Theme.fontMono : Theme.fontUi
                font.pixelSize: root.mono ? 12 : 14
                clip: true
                readOnly: root.readOnly
                selectByMouse: true
                onAccepted: root.accepted(text)
                onTextEdited: root.edited(text)
                Accessible.name: ph.text
            }
        }
        Text {
            id: suffixText
            visible: root.suffix !== ""
            text: root.suffix
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.t3
            font.family: Theme.fontMono
            font.pixelSize: 12
        }
    }
}
