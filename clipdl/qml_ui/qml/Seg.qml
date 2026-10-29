import QtQuick

// Segmented control with a sliding thumb that springs between options (like iOS / macOS).
// model: [{value, label, enabled}]   current: the selected value (string)
Rectangle {
    id: root
    property var model: []
    property string current: ""
    property int pad: 3
    signal picked(string value)

    implicitHeight: 34
    radius: Theme.radiusCtl
    color: Theme.card2A

    readonly property int count: model ? model.length : 0
    readonly property int idx: {
        for (let i = 0; i < count; i++)
            if (String(model[i].value) === String(current)) return i
        return -1
    }
    readonly property real cell: count > 0 ? (width - pad * 2) / count : 0

    Rectangle {
        id: thumb
        visible: root.idx >= 0
        y: root.pad
        height: root.height - root.pad * 2
        width: root.cell
        x: root.pad + Math.max(0, root.idx) * root.cell
        radius: Theme.radiusCtl - 3
        color: Theme.acc
        Behavior on x {
            enabled: root.visible
            SpringAnimation { spring: Theme.reduceMotion ? 12 : 5; damping: Theme.reduceMotion ? 1 : 0.34; epsilon: 0.25 }
        }
        Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
    }

    Repeater {
        model: root.model
        delegate: Item {
            required property var modelData
            required property int index
            x: root.pad + index * root.cell
            y: root.pad
            width: root.cell
            height: root.height - root.pad * 2
            opacity: modelData.enabled === false ? 0.35 : 1
            scale: ma.pressed ? 0.95 : 1
            Behavior on scale { SpringAnimation { spring: 5; damping: 0.4; epsilon: 0.002 } }
            Text {
                anchors.centerIn: parent
                text: parent.modelData.label
                font.family: Theme.fontUi
                font.pixelSize: 12
                font.weight: Font.DemiBold
                color: root.idx === parent.index ? Theme.accText : (ma.containsMouse ? Theme.text : Theme.t2)
                Behavior on color { ColorAnimation { duration: 180 } }
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                enabled: parent.modelData.enabled !== false
                cursorShape: Qt.PointingHandCursor
                onClicked: root.picked(String(parent.modelData.value))
            }
        }
    }
}
