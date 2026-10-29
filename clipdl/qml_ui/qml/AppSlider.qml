import QtQuick

// Thin Apple-style slider. Emits moved(value) while dragging.
Item {
    id: root
    property real from: 0
    property real to: 1
    property real value: 0
    property real step: 0          // 0 = continuous
    property bool isEnabled: true
    property string label: ""
    signal moved(real value)

    implicitHeight: 28
    implicitWidth: 200
    opacity: isEnabled ? 1 : 0.35

    readonly property real frac: to > from ? Math.max(0, Math.min(1, (value - from) / (to - from))) : 0

    function snap(v) {
        v = Math.max(from, Math.min(to, v))
        return step > 0 ? from + Math.round((v - from) / step) * step : v
    }

    Rectangle {
        id: groove
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: 5
        radius: 2.5
        color: Theme.card2
        Rectangle {
            width: parent.width * root.frac
            height: parent.height
            radius: 2.5
            color: Theme.acc
        }
    }
    Rectangle {
        id: knob
        width: ma.pressed ? 24 : 20
        height: width
        radius: width / 2
        color: "#ffffff"
        y: (root.height - height) / 2
        x: (root.width - 20) * root.frac - (width - 20) / 2
        Behavior on width { SpringAnimation { spring: 6; damping: 0.4; epsilon: 0.2 } }
        border.width: 1
        border.color: "#22000000"
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        enabled: root.isEnabled
        cursorShape: Qt.PointingHandCursor
        function setFrom(mx) {
            const f = Math.max(0, Math.min(1, (mx - 10) / Math.max(1, root.width - 20)))
            const v = root.snap(root.from + f * (root.to - root.from))
            if (v !== root.value) root.moved(v)
        }
        onPressed: (m) => setFrom(m.x)
        onPositionChanged: (m) => { if (pressed) setFrom(m.x) }
    }
    Accessible.role: Accessible.Slider
    Accessible.name: label
    activeFocusOnTab: true
    Keys.onLeftPressed: root.moved(root.snap(value - (step > 0 ? step : (to - from) / 20)))
    Keys.onRightPressed: root.moved(root.snap(value + (step > 0 ? step : (to - from) / 20)))
}
