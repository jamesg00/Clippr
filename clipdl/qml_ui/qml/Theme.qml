pragma Singleton
import QtQuick

// Every color the app uses lives here. Changing `id` re-targets the whole palette and every color
// cross-fades to its new value (see `blend` below), which is what gives theme changes their
// smooth Apple-style cross-fade. With "Reduce motion" on, the fade is shortened instead of removed.
QtObject {
    id: t

    property string themeKey: "mint"   // set from backend.themeId
    property bool dark: true            // resolved id for "auto" is handled in Main.qml
    property bool reduceMotion: false
    property real panelAlpha: 1.0       // 1 in Solid; = window opacity in Frosted / Clear
    readonly property int dur: reduceMotion ? 140 : 420

    readonly property var palettes: ({
        light:    { winS: "#f5f5f7", side: "#0a000000", card: "#ffffff", card2: "#e9e9ee", line: "#17000000",
                    text: "#1d1d1f", t2: "#55555b", t3: "#6a6a70", acc: "#0066d6", onAcc: "#ffffff", dark: false },
        graphite: { winS: "#1c1c1e", side: "#0affffff", card: "#2a2a2d", card2: "#38383c", line: "#1affffff",
                    text: "#f5f5f7", t2: "#b4b4ba", t3: "#9a9aa1", acc: "#0a84ff", onAcc: "#001224", dark: true },
        noir:     { winS: "#000000", side: "#0dffffff", card: "#0d0d0d", card2: "#1c1c1c", line: "#29ffffff",
                    text: "#ffffff", t2: "#c2c2c2", t3: "#a0a0a0", acc: "#ffffff", onAcc: "#000000", dark: true },
        paper:    { winS: "#ffffff", side: "#0a000000", card: "#f3f3f3", card2: "#e2e2e2", line: "#29000000",
                    text: "#000000", t2: "#3c3c3c", t3: "#5c5c5c", acc: "#000000", onAcc: "#ffffff", dark: false },
        mint:     { winS: "#060d09", side: "#09ffffff", card: "#0b1510", card2: "#14231b", line: "#14ffffff",
                    text: "#ecf2ee", t2: "#a3b8ac", t3: "#86998d", acc: "#2ee59d", onAcc: "#04140c", dark: true },
        midnight: { winS: "#12102a", side: "#0affffff", card: "#1b1838", card2: "#292552", line: "#1affffff",
                    text: "#f1eeff", t2: "#b9b2dc", t3: "#a29bc9", acc: "#b794ff", onAcc: "#170a33", dark: true },
        ocean:    { winS: "#08141f", side: "#0affffff", card: "#0e2233", card2: "#17344d", line: "#1affffff",
                    text: "#e8f6ff", t2: "#9db9cc", t3: "#86a3b7", acc: "#4fd1ff", onAcc: "#021824", dark: true },
        sunset:   { winS: "#1f1311", side: "#0affffff", card: "#2b1b17", card2: "#3c2620", line: "#1affffff",
                    text: "#fbefe9", t2: "#d0b3a8", t3: "#b99b90", acc: "#ff9f6b", onAcc: "#2a0f05", dark: true },
        rose:     { winS: "#1f1218", side: "#0affffff", card: "#2b1822", card2: "#3d2231", line: "#1affffff",
                    text: "#fdeef5", t2: "#d3aebf", t3: "#bb95a8", acc: "#ff7eb6", onAcc: "#2b0716", dark: true }
    })

    // "auto" follows the operating system; Main.qml passes the resolved id in here
    readonly property var p: palettes[themeKey] !== undefined ? palettes[themeKey] : palettes.mint


    // Theme changes cross-fade: `blend` runs 0 -> 1 while every color is mixed between the previous palette and
    // the new one. (Plain NumberAnimation instead of per-color Behaviors, which crash in a singleton QtObject.)
    property var prevP: palettes.mint
    property real blend: 1
    function mix(a, b, f) {
        const ca = Qt.color(a), cb = Qt.color(b)
        return Qt.rgba(ca.r + (cb.r - ca.r) * f, ca.g + (cb.g - ca.g) * f, ca.b + (cb.b - ca.b) * f,
                       ca.a + (cb.a - ca.a) * f)
    }
    function snapshot() {
        return { winS: winS, side: side, card: card, card2: card2, line: line, text: text, t2: t2, t3: t3,
                 acc: acc, onAcc: accText }
    }
    property bool started: false   // Main.qml sets this once the saved theme is applied, so startup doesn't fade
    property string shownKey: ""
    Component.onCompleted: if (shownKey === "") shownKey = themeKey
    onThemeKeyChanged: {
        if (!started) { prevP = p; blend = 1; shownKey = themeKey; return }
        // the colors above may already have jumped to the new palette here, so fade from the palette we were showing
        prevP = (blend >= 1 && palettes[shownKey] !== undefined) ? palettes[shownKey] : snapshot()
        shownKey = themeKey
        blend = 0
        fade.restart()
    }
    property NumberAnimation fadeAnim: NumberAnimation {
        id: fade
        target: t
        property: "blend"
        from: 0
        to: 1
        duration: t.dur
        easing.type: Easing.OutCubic
    }

    property color winS: mix(prevP.winS, p.winS, blend)
    property color side: mix(prevP.side, p.side, blend)
    property color card: mix(prevP.card, p.card, blend)
    property color card2: mix(prevP.card2, p.card2, blend)
    property color line: mix(prevP.line, p.line, blend)
    property color text: mix(prevP.text, p.text, blend)
    property color t2: mix(prevP.t2, p.t2, blend)
    property color t3: mix(prevP.t3, p.t3, blend)
    property color acc: mix(prevP.acc, p.acc, blend)
    property color accText: mix(prevP.onAcc, p.onAcc, blend)

    // derived colors (follow the animated values above, so they animate too)
    readonly property color accSoft: Qt.rgba(acc.r, acc.g, acc.b, 0.18)
    readonly property color cardA: Qt.rgba(card.r, card.g, card.b, panelAlpha)
    readonly property color card2A: Qt.rgba(card2.r, card2.g, card2.b, panelAlpha)
    readonly property color danger: dark ? "#ff6b6b" : "#c9302c"

    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

    // type scale + motion tokens shared by every screen
    property string fontUi: "Inter"
    property string fontMono: "Consolas"
    readonly property int radiusCard: 16
    readonly property int radiusCtl: 11
    readonly property int springMs: reduceMotion ? 120 : 260
}
