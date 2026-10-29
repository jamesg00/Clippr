import QtQuick
import QtQuick.Layouts

// Photoshop-style editor for the Resize tool.
// The artboard is the output picture. The image is a layer on it: drag to move, scale from the 8 handles,
// rotate with the knob (or drag just outside a corner), crop / extend the canvas with the tabs outside it.
// Shift / Alt modify gestures, the wheel zooms, empty space pans, double-click empty space fits the view,
// arrow keys nudge (Shift = 10 px), Ctrl+Z / Ctrl+Shift+Z undo / redo.
Item {
    id: root

    readonly property var st: tools.editor
    readonly property bool ok: st !== undefined && st.ok === true
    readonly property bool interactive: ok && st.locked !== true
    property var t: null                     // the transform being shown / edited (canvas px, Transform field names)
    property bool edited: false
    property bool lock: true                 // keep proportions
    property real zoom: 1
    property real panX: 0
    property real panY: 0
    property bool fitted: false
    property var drag: null
    property var hover: null
    property var guides: []
    property string hud: ""
    property real mx: 0
    property real my: 0
    property int lastId: -1
    property int lastToken: -1
    property var undoStacks: ({})
    property var redoStacks: ({})
    property int undoCount: 0
    readonly property int iw: ok ? Math.max(1, st.iw) : 1
    readonly property int ih: ok ? Math.max(1, st.ih) : 1
    readonly property real handle: 5
    readonly property real hitR: 8

    onStChanged: syncFromState()
    Component.onCompleted: syncFromState()
    function syncFromState() {
        if (drag) return
        const good = st !== undefined && st !== null && st.ok === true && st.t !== undefined
        if (good) {
            t = Object.assign({}, st.t)
            edited = st.edited === true
            if (st.id !== lastId || st.token !== lastToken) {
                lastId = st.id; lastToken = st.token
                fitted = false
                Qt.callLater(fitView)
                undoCount = (undoStacks[String(st.id)] || []).length
            }
        } else {
            t = null
            lastId = -1
        }
    }

    // ------------------------------------------------------------------ geometry helpers
    function rotp(x, y, deg) {
        const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a)
        return [x * c - y * s, x * s + y * c]
    }
    function half(tt) { tt = tt || t; return [iw * Math.abs(tt.sx) / 2, ih * Math.abs(tt.sy) / 2] }
    function layerPt(lx, ly, tt) { tt = tt || t; const r = rotp(lx, ly, tt.rot); return [tt.cx + r[0], tt.cy + r[1]] }
    function toLocal(x, y, tt) { tt = tt || t; return rotp(x - tt.cx, y - tt.cy, -tt.rot) }
    function c2w(x, y) { return [panX + x * zoom, panY + y * zoom] }
    function w2c(x, y) { return [(x - panX) / zoom, (y - panY) / zoom] }
    function bounds(tt) {
        const a = tt.rot * Math.PI / 180
        return [Math.abs(iw * tt.sx * Math.cos(a)) + Math.abs(ih * tt.sy * Math.sin(a)),
                Math.abs(iw * tt.sx * Math.sin(a)) + Math.abs(ih * tt.sy * Math.cos(a))]
    }

    function fitView() {
        if (!t || view.width < 10) return
        const m = 56
        zoom = Math.max(0.01, Math.min((view.width - 2 * m) / Math.max(1, t.canvas_w), (view.height - 2 * m) / Math.max(1, t.canvas_h)))
        panX = (view.width - t.canvas_w * zoom) / 2
        panY = (view.height - t.canvas_h * zoom) / 2
        fitted = true
    }

    function hit(px, py) {
        if (!t || !ok) return { k: "pan" }
        const h = half()
        for (let hx = -1; hx <= 1; hx++) for (let hy = -1; hy <= 1; hy++) {
            if (hx === 0 && hy === 0) continue
            const p = c2w.apply(null, layerPt(hx * h[0], hy * h[1]))
            if (Math.abs(p[0] - px) <= hitR && Math.abs(p[1] - py) <= hitR) return { k: "scale", hx: hx, hy: hy }
        }
        const kn = c2w.apply(null, layerPt(0, -h[1] - 30 / zoom))
        if (Math.hypot(kn[0] - px, kn[1] - py) <= hitR + 2) return { k: "rotate" }
        for (let ax = -1; ax <= 1; ax++) for (let ay = -1; ay <= 1; ay++) {
            if (ax === 0 && ay === 0) continue
            const p = c2w(t.canvas_w * (ax + 1) / 2, t.canvas_h * (ay + 1) / 2)
            if (Math.abs(p[0] + ax * 14 - px) <= hitR + 3 && Math.abs(p[1] + ay * 14 - py) <= hitR + 3) return { k: "canvas", ax: ax, ay: ay }
        }
        const c = w2c(px, py), l = toLocal(c[0], c[1])
        if (Math.abs(l[0]) <= h[0] && Math.abs(l[1]) <= h[1]) return { k: "move" }
        for (let hx = -1; hx <= 1; hx += 2) for (let hy = -1; hy <= 1; hy += 2) {
            const p = c2w.apply(null, layerPt(hx * h[0], hy * h[1]))
            if (Math.hypot(p[0] - px, p[1] - py) <= 26) return { k: "rotate" }
        }
        return { k: "pan" }
    }
    function sameHit(a, b) {
        if (!a || !b) return a === b
        return a.k === b.k && a.hx === b.hx && a.hy === b.hy && a.ax === b.ax && a.ay === b.ay
    }
    function cursorFor(h) {
        if (drag && drag.k === "pan") return Qt.ClosedHandCursor
        if (!h) return Qt.ArrowCursor
        if (h.k === "move") return Qt.SizeAllCursor
        if (h.k === "rotate") return Qt.CrossCursor
        if (h.k === "pan") return Qt.OpenHandCursor
        const rot = h.k === "scale" ? t.rot : 0
        let ang = (Math.atan2(h.k === "scale" ? h.hy : h.ay, h.k === "scale" ? h.hx : h.ax) * 180 / Math.PI + rot) % 180
        if (ang < 0) ang += 180
        if (ang < 22.5 || ang >= 157.5) return Qt.SizeHorCursor
        if (ang < 67.5) return Qt.SizeFDiagCursor
        if (ang < 112.5) return Qt.SizeVerCursor
        return Qt.SizeBDiagCursor
    }

    // ------------------------------------------------------------------ gestures (ported from the classic editor)
    function scaleGesture(t0, hx, hy, mx_, my_, mods) {
        const hw0 = iw * Math.abs(t0.sx) / 2, hh0 = ih * Math.abs(t0.sy) / 2
        const l = toLocal(mx_, my_, t0)
        const alt = (mods & Qt.AltModifier) !== 0
        const prop = lock !== ((mods & Qt.ShiftModifier) !== 0)
        const ax = alt ? 0 : -hx * hw0, ay = alt ? 0 : -hy * hh0
        const w0 = 2 * hw0, h0 = 2 * hh0
        let w = hx ? Math.max(1, ((l[0] - ax) * hx) * (alt ? 2 : 1)) : w0
        let h = hy ? Math.max(1, ((l[1] - ay) * hy) * (alt ? 2 : 1)) : h0
        if (prop) {
            const fw = w / w0, fh = h / h0
            let f
            if (hx && hy) f = Math.abs(fw - 1) >= Math.abs(fh - 1) ? fw : fh
            else f = hx ? fw : fh
            w = w0 * f; h = h0 * f
        }
        const sx = (t0.sx < 0 ? -1 : 1) * w / iw, sy = (t0.sy < 0 ? -1 : 1) * h / ih
        let clx = 0, cly = 0
        if (!alt) { clx = hx ? ax + hx * w / 2 : 0; cly = hy ? ay + hy * h / 2 : 0 }
        const r = rotp(clx, cly, t0.rot)
        return Object.assign({}, t0, { sx: sx, sy: sy, cx: t0.cx + r[0], cy: t0.cy + r[1] })
    }
    function canvasGesture(t0, ax, ay, dx, dy, mods) {
        const cw = t0.canvas_w, ch = t0.canvas_h
        let nw = ax ? Math.max(1, cw + dx * ax) : cw
        let nh = ay ? Math.max(1, ch + dy * ay) : ch
        if (lock !== ((mods & Qt.ShiftModifier) !== 0)) {
            const r = cw / ch
            if (ax && ay) { if (Math.abs(nw / cw - 1) >= Math.abs(nh / ch - 1)) nh = nw / r; else nw = nh * r }
            else if (ax) nh = nw / r
            else nw = nh * r
        }
        nw = Math.round(nw); nh = Math.round(nh)
        let cx = t0.cx, cy = t0.cy
        if (ax < 0) cx += nw - cw; else if (ax === 0) cx += (nw - cw) / 2
        if (ay < 0) cy += nh - ch; else if (ay === 0) cy += (nh - ch) / 2
        return Object.assign({}, t0, { canvas_w: nw, canvas_h: nh, cx: cx, cy: cy })
    }
    function snap(tt, mods) {
        let gs = []
        if (mods & Qt.ControlModifier) { guides = gs; return tt }
        const b = bounds(tt), tol = 7 / zoom
        let cx = tt.cx, cy = tt.cy
        const axes = [[[0, tt.canvas_w / 2, tt.canvas_w], b[0], "x"], [[0, tt.canvas_h / 2, tt.canvas_h], b[1], "y"]]
        for (const a of axes) {
            const c = a[2] === "x" ? cx : cy
            let best = null
            for (const tgt of a[0]) for (const off of [-a[1] / 2, 0, a[1] / 2]) {
                const d = tgt - (c + off)
                if (Math.abs(d) <= tol && (best === null || Math.abs(d) < Math.abs(best[0]))) best = [d, tgt]
            }
            if (best) { if (a[2] === "x") cx += best[0]; else cy += best[0]; gs.push({ axis: a[2], v: best[1] }) }
        }
        guides = gs
        return Object.assign({}, tt, { cx: cx, cy: cy })
    }

    // ------------------------------------------------------------------ commit / undo
    function copyT() { return Object.assign({}, t) }
    function push() {
        if (!t || !ok) return
        const k = String(st.id)
        const a = (undoStacks[k] || []).slice()
        a.push(copyT())
        undoStacks[k] = a.slice(-60)
        redoStacks[k] = []
        refreshUndo()
    }
    function refreshUndo() { undoCount = ok ? (undoStacks[String(st.id)] || []).length : 0 }
    function commit(nt) {
        t = nt
        edited = true
        tools.setEdit(st.id, nt)
    }
    function undo() {
        if (!ok) return
        const k = String(st.id), a = (undoStacks[k] || []).slice()
        if (!a.length) return
        const r = (redoStacks[k] || []).slice(); r.push(copyT()); redoStacks[k] = r
        const prev = a.pop(); undoStacks[k] = a
        refreshUndo(); commit(prev)
    }
    function redo() {
        if (!ok) return
        const k = String(st.id), r = (redoStacks[k] || []).slice()
        if (!r.length) return
        const a = (undoStacks[k] || []).slice(); a.push(copyT()); undoStacks[k] = a
        const nxt = r.pop(); redoStacks[k] = r
        refreshUndo(); commit(nxt)
    }
    function setSize(which, val) {
        if (!t || !(val >= 1)) return
        let fx = which === "w" ? val / t.canvas_w : 1, fy = which === "h" ? val / t.canvas_h : 1
        if (lock) { fx = fy = (which === "w" ? fx : fy) }
        push()
        commit(Object.assign({}, t, { canvas_w: Math.max(1, Math.round(t.canvas_w * fx)), canvas_h: Math.max(1, Math.round(t.canvas_h * fy)),
                                      cx: t.cx * fx, cy: t.cy * fy, sx: t.sx * fx, sy: t.sy * fy }))
    }
    function setScalePct(v) {
        if (!t || !(v > 0)) return
        const s = v / 100, ratio = t.sx ? Math.abs(t.sy / t.sx) : 1
        push()
        commit(Object.assign({}, t, { sx: (t.sx < 0 ? -1 : 1) * s, sy: (t.sy < 0 ? -1 : 1) * s * (lock ? 1 : ratio) }))
    }
    function setRot(v) { if (!t) return; push(); commit(Object.assign({}, t, { rot: Math.max(-180, Math.min(180, v)) })) }
    function setBg(v) { if (!t) return; push(); commit(Object.assign({}, t, { bg: v })) }
    function fitT(cover) {
        const b = bounds(Object.assign({}, t, { sx: 1, sy: 1 }))
        const s = (cover ? Math.max : Math.min)(t.canvas_w / b[0], t.canvas_h / b[1])
        return Object.assign({}, t, { sx: s, sy: s, cx: t.canvas_w / 2, cy: t.canvas_h / 2 })
    }
    function action(key) {
        if (!t || !ok) return
        if (key === "undo") { undo(); return }
        if (key === "reset") { tools.resetEdit(st.id); edited = false; return }
        push()
        let nt = t
        if (key === "rot_l" || key === "rot_r") {
            const r = (((t.rot + (key === "rot_l" ? -90 : 90)) + 180) % 360 + 360) % 360 - 180
            const b = bounds(t)
            const fills = Math.abs(b[0] - t.canvas_w) < 2 && Math.abs(b[1] - t.canvas_h) < 2
            nt = fills ? Object.assign({}, t, { rot: r, canvas_w: t.canvas_h, canvas_h: t.canvas_w, cx: t.canvas_h / 2, cy: t.canvas_w / 2 })
                       : Object.assign({}, t, { rot: r })
        } else if (key === "flip_h") nt = Object.assign({}, t, { flip_h: !t.flip_h })
        else if (key === "flip_v") nt = Object.assign({}, t, { flip_v: !t.flip_v })
        else if (key === "fit") nt = fitT(false)
        else if (key === "fill") nt = fitT(true)
        else if (key === "crop") {
            const b = bounds(t)
            nt = Object.assign({}, t, { canvas_w: Math.max(1, Math.round(b[0])), canvas_h: Math.max(1, Math.round(b[1])), cx: b[0] / 2, cy: b[1] / 2 })
        }
        commit(nt)
        if (key === "rot_l" || key === "rot_r" || key === "crop") Qt.callLater(fitView)
    }

    // ------------------------------------------------------------------ small parts
    component NumField: FieldBox {
        id: nf
        property real value: 0
        property int decimals: 0
        property real lo: 1
        property real hi: 30000
        signal commitValue(real v)
        implicitHeight: 32
        implicitWidth: 96
        mono: true
        function sync() { if (!input.activeFocus) text = decimals > 0 ? value.toFixed(decimals) : String(Math.round(value)) }
        onValueChanged: sync()
        Component.onCompleted: sync()
        input.onActiveFocusChanged: if (!input.activeFocus) sync()
        input.onEditingFinished: {
            const v = parseFloat(text)
            if (!isNaN(v)) commitValue(Math.min(hi, Math.max(lo, v)))
            Qt.callLater(sync)
        }
        input.inputMethodHints: Qt.ImhFormattedNumbersOnly
    }
    component Lbl: Text { color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 11; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignVCenter }
    component IconBtn: Rectangle {
        id: ib
        property string d: ""
        property string tip: ""
        property bool isEnabled: true
        signal clicked()
        implicitWidth: 32; implicitHeight: 32; radius: 9
        color: ma2.containsMouse && isEnabled ? Theme.card2A : "transparent"
        opacity: isEnabled ? 1 : 0.35
        Icon { anchors.centerIn: parent; d: ib.d; size: 16; color: Theme.t2 }
        MouseArea { id: ma2; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: if (ib.isEnabled) ib.clicked() }
        Accessible.role: Accessible.Button
        Accessible.name: ib.tip
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        // ---------------------------------------------------------------- options bar
        Flow {
            Layout.fillWidth: true
            Layout.leftMargin: 10; Layout.rightMargin: 10; Layout.topMargin: 10
            spacing: 6
            opacity: root.interactive ? 1 : 0.45
            Lbl { text: "W"; height: 32; verticalAlignment: Text.AlignVCenter }
            NumField { value: root.t ? root.t.canvas_w : 0; suffix: "px"; enabled: root.interactive; onCommitValue: (v) => root.setSize("w", v) }
            Rectangle {
                implicitWidth: 30; implicitHeight: 30; radius: 9
                color: root.lock ? Theme.accSoft : "transparent"
                border.width: 1; border.color: root.lock ? Theme.alpha(Theme.acc, 0.5) : Theme.line
                Icon { anchors.centerIn: parent; d: root.lock ? Icons.link : Icons.unlink; size: 15; color: root.lock ? Theme.acc : Theme.t3 }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.lock = !root.lock }
                Accessible.role: Accessible.CheckBox
                Accessible.name: "Keep proportions"
            }
            Lbl { text: "H"; height: 32; verticalAlignment: Text.AlignVCenter }
            NumField { value: root.t ? root.t.canvas_h : 0; suffix: "px"; enabled: root.interactive; onCommitValue: (v) => root.setSize("h", v) }
            Item { width: 6; height: 1 }
            Lbl { text: "SCALE"; height: 32; verticalAlignment: Text.AlignVCenter }
            NumField { implicitWidth: 84; decimals: 1; lo: 1; hi: 5000; value: root.t ? Math.abs(root.t.sx) * 100 : 100; suffix: "%"; enabled: root.interactive; onCommitValue: (v) => root.setScalePct(v) }
            Lbl { text: "ANGLE"; height: 32; verticalAlignment: Text.AlignVCenter }
            NumField { implicitWidth: 76; decimals: 1; lo: -180; hi: 180; value: root.t ? root.t.rot : 0; suffix: "°"; enabled: root.interactive; onCommitValue: (v) => root.setRot(v) }
            Rectangle {
                implicitWidth: badge.implicitWidth + 16; implicitHeight: 24; radius: 12
                color: root.edited ? Theme.accSoft : Theme.card2A
                Text { id: badge; anchors.centerIn: parent; text: root.edited ? "Custom" : "Batch settings"; color: root.edited ? Theme.acc : Theme.t2; font.family: Theme.fontUi; font.pixelSize: 11; font.weight: Font.DemiBold }
            }
        }

        // ---------------------------------------------------------------- canvas
        Item {
            id: view
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 10; Layout.rightMargin: 10
            Layout.minimumHeight: 180
            clip: true
            focus: true
            onWidthChanged: if (!root.fitted) Qt.callLater(root.fitView)
            onHeightChanged: if (!root.fitted) Qt.callLater(root.fitView)

            Rectangle { anchors.fill: parent; radius: 12; color: Theme.dark ? "#0b0f0d" : "#e6e9e7"; border.width: 1; border.color: Theme.line }

            Text {
                visible: !root.ok
                anchors.centerIn: parent
                text: root.st && root.st.id !== undefined ? "Couldn't open that picture for editing." : "Pick a picture in the list to edit it"
                color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 14
            }

            // one layer of the picture (also used as the faint ghost outside the canvas)
            component Layer: Item {
                property real ox: 0
                property real oy: 0
                visible: root.ok && root.t !== null
                x: root.panX + (root.t ? root.t.cx : 0) * root.zoom - ox
                y: root.panY + (root.t ? root.t.cy : 0) * root.zoom - oy
                rotation: root.t ? root.t.rot : 0
                Item {
                    transform: Scale {
                        xScale: root.t ? root.zoom * Math.abs(root.t.sx) * (root.t.flip_h ? -1 : 1) : 1
                        yScale: root.t ? root.zoom * Math.abs(root.t.sy) * (root.t.flip_v ? -1 : 1) : 1
                    }
                    Image {
                        x: -root.iw / 2; y: -root.ih / 2
                        width: root.iw; height: root.ih
                        source: root.ok ? "image://preview/" + root.st.token : ""
                        cache: false
                        smooth: true
                        mipmap: true
                    }
                }
            }

            // artboard
            Rectangle {
                id: art
                visible: root.ok && root.t !== null
                x: root.panX; y: root.panY
                width: root.t ? root.t.canvas_w * root.zoom : 0
                height: root.t ? root.t.canvas_h * root.zoom : 0
                color: root.t && root.t.bg !== "transparent" ? root.t.bg : "#262e2a"
                Canvas {
                    id: checker
                    anchors.fill: parent
                    visible: root.t && root.t.bg === "transparent"
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onVisibleChanged: requestPaint()
                    onPaint: {
                        const c = getContext("2d")
                        c.reset()
                        c.fillStyle = "#1a201d"
                        const s = 12
                        for (let y = 0, r = 0; y < height; y += s, r++)
                            for (let x = (r % 2) * s; x < width; x += s * 2) c.fillRect(x, y, s, s)
                    }
                }
            }
            Layer { opacity: 0.22 }
            Item {
                x: art.x; y: art.y; width: art.width; height: art.height
                clip: true
                visible: art.visible
                Layer { ox: art.x; oy: art.y }
            }
            Rectangle { x: art.x; y: art.y; width: art.width; height: art.height; visible: art.visible; color: "transparent"; border.width: 1; border.color: "#96ffffff" }
            Text {
                visible: art.visible
                x: art.x; y: art.y + art.height + 26; width: art.width
                horizontalAlignment: Text.AlignHCenter
                text: root.t ? root.t.canvas_w + " × " + root.t.canvas_h + " px" : ""
                color: Theme.t2; font.family: Theme.fontMono; font.pixelSize: 11
            }

            // snap guides
            Repeater {
                model: root.guides
                Rectangle {
                    required property var modelData
                    readonly property bool vert: modelData.axis === "x"
                    x: vert ? root.c2w(modelData.v, 0)[0] : 0
                    y: vert ? 0 : root.c2w(0, modelData.v)[1]
                    width: vert ? 1 : view.width
                    height: vert ? view.height : 1
                    color: "#FF4FD8"
                }
            }

            // layer frame, handles and rotate knob
            Item {
                id: frame
                visible: root.ok && root.t !== null && root.interactive
                readonly property real hwz: root.t ? root.half()[0] * root.zoom : 0
                readonly property real hhz: root.t ? root.half()[1] * root.zoom : 0
                x: root.panX + (root.t ? root.t.cx : 0) * root.zoom
                y: root.panY + (root.t ? root.t.cy : 0) * root.zoom
                rotation: root.t ? root.t.rot : 0
                Rectangle { x: -frame.hwz; y: -frame.hhz; width: frame.hwz * 2; height: frame.hhz * 2; color: "transparent"; border.width: 1.5; border.color: Theme.acc }
                Rectangle { x: -0.75; y: -frame.hhz - 30; width: 1.5; height: 30; color: Theme.acc }
                Rectangle {
                    readonly property bool hot: root.hover && root.hover.k === "rotate"
                    x: -6; y: -frame.hhz - 36; width: 12; height: 12; radius: 6
                    color: hot ? Theme.acc : Theme.accText; border.width: 1.5; border.color: Theme.acc
                }
                Repeater {
                    model: [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]]
                    Rectangle {
                        required property var modelData
                        readonly property bool hot: root.hover && root.hover.k === "scale" && root.hover.hx === modelData[0] && root.hover.hy === modelData[1]
                        x: modelData[0] * frame.hwz - root.handle; y: modelData[1] * frame.hhz - root.handle
                        width: root.handle * 2; height: root.handle * 2
                        color: hot ? Theme.acc : "#ffffff"; border.width: 1.5; border.color: Theme.acc
                    }
                }
            }

            // canvas tabs, just outside the artboard
            Repeater {
                model: root.ok && root.t && root.interactive ? [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]] : []
                Rectangle {
                    required property var modelData
                    readonly property int ax: modelData[0]
                    readonly property int ay: modelData[1]
                    readonly property bool hot: root.hover && root.hover.k === "canvas" && root.hover.ax === ax && root.hover.ay === ay
                    readonly property real w: ax && ay ? 9 : (ax ? 6 : 22)
                    readonly property real h: ax && ay ? 9 : (ax ? 22 : 6)
                    width: w; height: h; radius: ax && ay ? 4.5 : 3
                    x: root.panX + root.t.canvas_w * root.zoom * (ax + 1) / 2 + ax * 14 - w / 2
                    y: root.panY + root.t.canvas_h * root.zoom * (ay + 1) / 2 + ay * 14 - h / 2
                    color: hot ? Theme.acc : "#e8f0ec"; border.width: 1; border.color: "#a0000000"
                }
            }

            // hud chip while dragging, zoom chip always
            Rectangle {
                visible: root.hud !== ""
                x: Math.min(view.width - width - 6, root.mx + 16); y: Math.min(view.height - height - 6, root.my + 18)
                width: hudText.implicitWidth + 16; height: 22; radius: 6
                color: "#e6030c07"; border.width: 1; border.color: Theme.alpha(Theme.acc, 0.5)
                Text { id: hudText; anchors.centerIn: parent; text: root.hud; color: Theme.acc; font.family: Theme.fontMono; font.pixelSize: 11 }
            }
            Rectangle {
                visible: root.ok
                anchors { right: parent.right; bottom: parent.bottom; margins: 8 }
                width: zoomText.implicitWidth + 16; height: 22; radius: 6
                color: "#e6030c07"; border.width: 1; border.color: Theme.line
                Text { id: zoomText; anchors.centerIn: parent; text: Math.round(root.zoom * 100) + "%"; color: Theme.t2; font.family: Theme.fontMono; font.pixelSize: 11 }
            }

            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                cursorShape: root.cursorFor(root.drag ? root.drag.h : root.hover)

                onPressed: (m) => {
                    view.forceActiveFocus()
                    root.mx = m.x; root.my = m.y
                    if (!root.ok || !root.t) return
                    if (m.button === Qt.MiddleButton || !root.interactive) {
                        root.drag = { k: "pan", h: { k: "pan" }, p0: [m.x, m.y], pan0: [root.panX, root.panY] }
                        return
                    }
                    const h = root.hit(m.x, m.y)
                    root.drag = { k: h.k, h: h, p0: [m.x, m.y], t0: root.copyT(), pan0: [root.panX, root.panY] }
                    if (h.k !== "pan") root.push()
                }
                onPositionChanged: (m) => {
                    root.mx = m.x; root.my = m.y
                    const d = root.drag
                    if (!d) {
                        const h = root.hit(m.x, m.y)
                        if (!root.sameHit(h, root.hover)) root.hover = h
                        return
                    }
                    if (d.k === "pan") {
                        root.panX = d.pan0[0] + m.x - d.p0[0]
                        root.panY = d.pan0[1] + m.y - d.p0[1]
                        root.fitted = true
                        return
                    }
                    const t0 = d.t0
                    const c = root.w2c(m.x, m.y), c0 = root.w2c(d.p0[0], d.p0[1])
                    const mods = m.modifiers
                    let nt = null
                    if (d.k === "move") {
                        let dx = c[0] - c0[0], dy = c[1] - c0[1]
                        if (mods & Qt.ShiftModifier) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0 }
                        nt = root.snap(Object.assign({}, t0, { cx: t0.cx + dx, cy: t0.cy + dy }), mods)
                        root.hud = "x " + Math.round(nt.cx - root.iw * Math.abs(nt.sx) / 2) + "  y " + Math.round(nt.cy - root.ih * Math.abs(nt.sy) / 2)
                    } else if (d.k === "rotate") {
                        const a0 = Math.atan2(c0[1] - t0.cy, c0[0] - t0.cx) * 180 / Math.PI
                        const a1 = Math.atan2(c[1] - t0.cy, c[0] - t0.cx) * 180 / Math.PI
                        let r = t0.rot + (a1 - a0)
                        if (mods & Qt.ShiftModifier) r = Math.round(r / 15) * 15
                        r = (((r + 180) % 360) + 360) % 360 - 180
                        nt = Object.assign({}, t0, { rot: r })
                        root.hud = r.toFixed(1) + "°"
                    } else if (d.k === "scale") {
                        nt = root.scaleGesture(t0, d.h.hx, d.h.hy, c[0], c[1], mods)
                        root.hud = Math.round(root.iw * Math.abs(nt.sx)) + " × " + Math.round(root.ih * Math.abs(nt.sy)) + " px  ·  " + (Math.abs(nt.sx) * 100).toFixed(0) + "%"
                    } else if (d.k === "canvas") {
                        nt = root.canvasGesture(t0, d.h.ax, d.h.ay, c[0] - c0[0], c[1] - c0[1], mods)
                        root.hud = nt.canvas_w + " × " + nt.canvas_h + " px"
                    }
                    if (nt) root.commit(nt)
                }
                onReleased: (m) => {
                    root.drag = null
                    root.guides = []
                    root.hud = ""
                    root.hover = root.hit(m.x, m.y)
                }
                onExited: if (!root.drag) root.hover = null
                onDoubleClicked: (m) => { if (root.hit(m.x, m.y).k === "pan") root.fitView() }

                WheelHandler {
                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                    onWheel: (e) => {
                        if (!root.t) return
                        const f = Math.pow(1.0015, e.angleDelta.y)
                        const c = root.w2c(e.x, e.y)
                        root.zoom = Math.max(0.02, Math.min(32, root.zoom * f))
                        root.panX = e.x - c[0] * root.zoom
                        root.panY = e.y - c[1] * root.zoom
                        root.fitted = true
                    }
                }
            }

            Keys.onPressed: (e) => {
                if (!root.interactive || !root.t) return
                if ((e.modifiers & Qt.ControlModifier) && e.key === Qt.Key_Z) {
                    if (e.modifiers & Qt.ShiftModifier) root.redo(); else root.undo()
                    e.accepted = true
                    return
                }
                const step = (e.modifiers & Qt.ShiftModifier) ? 10 : 1
                const dx = e.key === Qt.Key_Left ? -step : (e.key === Qt.Key_Right ? step : 0)
                const dy = e.key === Qt.Key_Up ? -step : (e.key === Qt.Key_Down ? step : 0)
                if (dx || dy) {
                    root.push()
                    root.commit(Object.assign({}, root.t, { cx: root.t.cx + dx, cy: root.t.cy + dy }))
                    e.accepted = true
                }
            }
        }

        // ---------------------------------------------------------------- tool bar
        Flow {
            Layout.fillWidth: true
            Layout.leftMargin: 10; Layout.rightMargin: 10
            spacing: 4
            opacity: root.interactive ? 1 : 0.45
            IconBtn { d: Icons.rotateCcw; tip: "Rotate left 90°"; isEnabled: root.interactive; onClicked: root.action("rot_l") }
            IconBtn { d: Icons.rotateCw; tip: "Rotate right 90°"; isEnabled: root.interactive; onClicked: root.action("rot_r") }
            IconBtn { d: Icons.flipH; tip: "Flip horizontally"; isEnabled: root.interactive; onClicked: root.action("flip_h") }
            IconBtn { d: Icons.flipV; tip: "Flip vertically"; isEnabled: root.interactive; onClicked: root.action("flip_v") }
            IconBtn { d: Icons.undo; tip: "Undo"; isEnabled: root.interactive && root.undoCount > 0; onClicked: root.action("undo") }
            Item { width: 6; height: 1 }
            Btn { compact: true; text: "Fit"; isEnabled: root.interactive; onClicked: root.action("fit") }
            Btn { compact: true; text: "Fill"; isEnabled: root.interactive; onClicked: root.action("fill") }
            Btn { compact: true; text: "Crop to image"; isEnabled: root.interactive; onClicked: root.action("crop") }
            Btn { compact: true; text: "Reset"; isEnabled: root.interactive && root.edited; onClicked: root.action("reset") }
            Seg {
                width: 180
                implicitHeight: 32
                model: [{ value: "transparent", label: "Clear" }, { value: "#ffffff", label: "White" }, { value: "#000000", label: "Black" }]
                current: root.t ? root.t.bg : "transparent"
                enabled: root.interactive
                onPicked: (v) => root.setBg(v)
            }
            Btn { compact: true; text: "Apply to all"; iconPath: Icons.layers; isEnabled: root.interactive && root.edited; onClicked: tools.applyEditToAll(root.st.id) }
        }
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 12; Layout.rightMargin: 12; Layout.bottomMargin: 8
            wrapMode: Text.WordWrap
            text: "Drag the picture to move it · white handles scale it · the round knob rotates · tabs outside the canvas crop or extend it · Shift and Alt modify · wheel zooms"
            color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 11
        }
    }
}
