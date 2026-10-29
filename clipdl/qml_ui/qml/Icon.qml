import QtQuick
import QtQuick.Shapes

// Stroke icon from a 24x24 SVG path (lucide style). `filled` icons use the color as fill instead.
Item {
    id: root
    property string d: ""
    property color color: Theme.text
    property real size: 18
    property real strokeWidth: 2
    property bool filled: false

    width: size
    height: size

    Shape {
        width: 24
        height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.filled ? "transparent" : root.color
            strokeWidth: root.strokeWidth
            fillColor: root.filled ? root.color : "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.d }
        }
    }
}
