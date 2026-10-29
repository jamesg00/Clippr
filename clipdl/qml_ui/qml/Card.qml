import QtQuick

// A rounded panel. It thins out together with the window when the opacity slider is lowered.
Rectangle {
    property bool raised: false
    radius: Theme.radiusCard
    color: raised ? Theme.card2A : Theme.cardA
    border.width: 1
    border.color: Theme.line
}
