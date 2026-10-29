import QtQuick
import QtQuick.Layouts

// To MP3, Convert, Resize and Compress. A queue on the left (drop files here), the options and the start button on the right.
Item {
    id: root
    property string key: "mp3"

    readonly property var info: ({
        mp3:      { title: "To MP3", blurb: "Save the audio from YouTube, Instagram, X or SoundCloud links. Paste several and they download one after another.", icon: Icons.music,
                    dropTitle: "Paste links to save their audio", dropHint: "YouTube, Instagram, X and SoundCloud.", btn: "Paste from clipboard" },
        convert:  { title: "Convert", blurb: "Video, audio and pictures to other formats. Each kind has its own target, so a mixed list converts in one go.", icon: Icons.convert,
                    dropTitle: "Drop videos, audio or pictures", dropHint: "MP4, MOV, MP3, WAV, FLAC and PNG, JPG, WebP. Mix them freely.", btn: "Choose files" },
        resize:   { title: "Resize", blurb: "Make pictures bigger or smaller by percent, to fit a box, or to an exact size.", icon: Icons.resize,
                    dropTitle: "Drop pictures to resize", dropHint: "PNG, JPG, WebP, GIF, BMP and more.", btn: "Choose pictures" },
        compress: { title: "Compress", blurb: "Shrink PDFs, pictures, videos and audio. Anything else is packed into a ZIP.", icon: Icons.compress,
                    dropTitle: "Drop files to make them smaller", dropHint: "PDFs, pictures, videos and audio get re-compressed.", btn: "Choose files" }
    })
    readonly property var cur: info[key] !== undefined ? info[key] : info.mp3
    readonly property var o: tools.options
    readonly property bool isLinks: key === "mp3"
    readonly property var videoFormats: ["mp4", "mkv", "webm", "mov", "avi", "gif"]

    onKeyChanged: tools.setSession(key)
    Component.onCompleted: tools.setSession(key)

    // small labelled group in the options column
    component Group: ColumnLayout {
        property string title: ""
        property string note: ""
        default property alias content: slot.data
        Layout.fillWidth: true
        spacing: 7
        Text { text: parent.title.toUpperCase(); color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.8 }
        ColumnLayout { id: slot; Layout.fillWidth: true; spacing: 8 }
        Text { visible: parent.note !== ""; text: parent.note; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 12 }
    }
    component ToggleRow: RowLayout {
        id: tr
        property string title: ""
        property string sub: ""
        property bool checked: false
        signal toggled(bool v)
        Layout.fillWidth: true
        spacing: 10
        ColumnLayout {
            Layout.fillWidth: true; spacing: 1
            Text { text: tr.title; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 13; font.weight: Font.Medium }
            Text { visible: tr.sub !== ""; text: tr.sub; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 11 }
        }
        AppSwitch { checked: tr.checked; label: tr.title; onToggled: (v) => tr.toggled(v) }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
        anchors.topMargin: 34
        spacing: 14

        ColumnLayout {
            spacing: 4
            Layout.topMargin: 4
            Text { text: root.cur.title; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 28; font.weight: Font.Bold; topPadding: 2 }
            Text { Layout.fillWidth: true; text: root.cur.blurb; wrapMode: Text.WordWrap; color: Theme.t2; font.family: Theme.fontUi; font.pixelSize: 14 }
        }

        // link bar: only where links are needed
        RowLayout {
            visible: root.isLinks
            Layout.fillWidth: true
            spacing: 8
            FieldBox {
                id: linkField
                Layout.fillWidth: true
                iconPath: Icons.link
                placeholder: "Paste a YouTube, Instagram, X or SoundCloud link"
                onAccepted: (t) => { tools.addLinks(t); text = "" }
            }
            Btn { text: "Paste"; onClicked: tools.pasteLinks() }
            Btn { text: "Add"; primary: true; isEnabled: linkField.text.trim() !== ""; onClicked: { tools.addLinks(linkField.text); linkField.text = "" } }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            // ------------------------------------------------------------------ editor (Resize) + queue
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14

            Card {  // the picture editor
                visible: root.key === "resize" && tools.totalCount > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 300
                clip: true
                ImageEditor { anchors.fill: parent }
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: root.key === "resize" && tools.totalCount > 0 ? 150 : -1
                Layout.maximumHeight: root.key === "resize" && tools.totalCount > 0 ? 170 : 100000
                clip: true
                border.width: tools.totalCount === 0 ? 1.5 : 1
                border.color: dz.containsDrag ? Theme.acc : Theme.line

                // empty state
                ColumnLayout {
                    visible: tools.totalCount === 0
                    anchors.centerIn: parent
                    spacing: 10
                    width: Math.min(parent.width - 40, 420)
                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 64; height: 64; radius: 20; color: Theme.accSoft
                        Icon { anchors.centerIn: parent; d: root.cur.icon; size: 28; color: Theme.acc }
                    }
                    Text { Layout.alignment: Qt.AlignHCenter; text: root.cur.dropTitle; color: Theme.text; font.family: Theme.fontUi; font.pixelSize: 18; font.weight: Font.DemiBold }
                    Text { Layout.alignment: Qt.AlignHCenter; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; text: root.cur.dropHint; color: Theme.t2; font.family: Theme.fontUi; font.pixelSize: 13 }
                    Btn {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: 4
                        text: root.cur.btn
                        primary: true
                        onClicked: root.isLinks ? tools.pasteLinks() : tools.browse()
                    }
                }

                // list
                ListView {
                    id: list
                    visible: tools.totalCount > 0
                    anchors.fill: parent
                    anchors.margins: 10
                    anchors.bottomMargin: 54
                    model: tools.items
                    spacing: 6
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 } NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: 240; easing.type: Easing.OutBack } }
                    remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 160 } }
                    displaced: Transition { SpringAnimation { property: "y"; spring: 5; damping: 0.4; epsilon: 0.25 } }

                    delegate: Rectangle {
                        id: row
                        required property int iid
                        required property string name
                        required property string sub
                        required property string status
                        required property real pct
                        required property string text
                        required property string resultText
                        required property string resultPath
                        width: list.width
                        height: 62
                        radius: Theme.radiusCtl + 2
                        color: Theme.card2A
                        border.width: 1
                        border.color: status === "error" ? Theme.alpha(Theme.danger, 0.5) : Theme.line
                        Behavior on border.color { ColorAnimation { duration: 200 } }

                        readonly property bool picked: root.key === "resize" && tools.selectedId === iid
                        Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; visible: row.picked; border.width: 2; border.color: Theme.acc }
                        MouseArea { anchors.fill: parent; enabled: root.key === "resize"; cursorShape: Qt.PointingHandCursor; onClicked: tools.selectItem(row.iid) }

                        Rectangle {  // leading icon / state
                            id: lead
                            x: 12; anchors.verticalCenter: parent.verticalCenter
                            width: 36; height: 36; radius: 11
                            color: row.status === "error" ? Theme.alpha(Theme.danger, 0.16) : Theme.accSoft
                            Behavior on color { ColorAnimation { duration: 220 } }
                            Icon {
                                anchors.centerIn: parent
                                size: 17
                                strokeWidth: row.status === "done" ? 3 : 2
                                d: row.status === "done" ? Icons.check : (row.status === "error" ? Icons.alert : (root.isLinks ? Icons.link : root.cur.icon))
                                color: row.status === "error" ? Theme.danger : Theme.acc
                            }
                        }

                        ColumnLayout {
                            anchors { left: lead.right; leftMargin: 12; right: actions.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                            spacing: 3
                            Text {
                                Layout.fillWidth: true
                                text: row.name
                                elide: Text.ElideMiddle
                                color: Theme.text
                                font.family: Theme.fontUi; font.pixelSize: 13; font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: row.status !== "running"
                                elide: Text.ElideRight
                                text: row.status === "done" ? row.resultText : (row.status === "error" ? row.text : (row.text !== "" ? row.text : row.sub))
                                color: row.status === "error" ? Theme.danger : (row.status === "done" ? Theme.t2 : Theme.t3)
                                font.family: Theme.fontUi; font.pixelSize: 12
                            }
                            RowLayout {  // running: bar and text
                                visible: row.status === "running"
                                Layout.fillWidth: true
                                spacing: 10
                                Rectangle {
                                    id: groove
                                    Layout.fillWidth: true
                                    height: 5; radius: 2.5
                                    color: Theme.card2
                                    clip: true
                                    Rectangle {
                                        id: fill
                                        height: parent.height; radius: 2.5
                                        color: Theme.acc
                                        width: row.pct < 0 ? groove.width * 0.3 : groove.width * Math.max(0.02, row.pct / 100)
                                        Behavior on width { enabled: row.pct >= 0; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                                        SequentialAnimation on x {
                                            running: row.pct < 0 && row.status === "running"
                                            loops: Animation.Infinite
                                            NumberAnimation { from: 0; to: groove.width * 0.7; duration: 900; easing.type: Easing.InOutSine }
                                            NumberAnimation { from: groove.width * 0.7; to: 0; duration: 900; easing.type: Easing.InOutSine }
                                        }
                                    }
                                }
                                Text { text: row.text; Layout.maximumWidth: 200; elide: Text.ElideRight; color: Theme.t2; font.family: Theme.fontMono; font.pixelSize: 11 }
                            }
                        }

                        Row {
                            id: actions
                            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                            spacing: 6
                            Btn {
                                visible: row.status === "done" && row.resultPath !== ""
                                anchors.verticalCenter: parent.verticalCenter
                                compact: true; text: "Show"; iconPath: Icons.folder
                                onClicked: tools.reveal(row.iid)
                            }
                            Item {
                                visible: row.status !== "running"
                                width: 28; height: 28
                                anchors.verticalCenter: parent.verticalCenter
                                Rectangle { anchors.fill: parent; radius: 14; color: Theme.text; opacity: xma.containsMouse ? 0.08 : 0; Behavior on opacity { NumberAnimation { duration: 120 } } }
                                Icon { anchors.centerIn: parent; d: Icons.x; size: 14; color: Theme.t3 }
                                MouseArea { id: xma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tools.remove(row.iid) }
                                Accessible.role: Accessible.Button
                                Accessible.name: "Remove"
                            }
                        }
                    }
                }

                // list footer: add more / clear finished
                RowLayout {
                    visible: tools.totalCount > 0
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 10 }
                    spacing: 8
                    Btn { visible: !root.isLinks; compact: true; text: "Add files"; iconPath: Icons.upload; isEnabled: !tools.running; onClicked: tools.browse() }
                    Btn { visible: root.isLinks; compact: true; text: "Paste links"; iconPath: Icons.link; onClicked: tools.pasteLinks() }
                    Btn { compact: true; text: "Clear finished"; isEnabled: tools.doneCount > 0; onClicked: tools.clearFinished() }
                    Item { Layout.fillWidth: true }
                    Text { text: tools.summaryText; color: Theme.t2; font.family: Theme.fontUi; font.pixelSize: 12; elide: Text.ElideLeft; Layout.maximumWidth: 360 }
                }

                DropArea {
                    id: dz
                    anchors.fill: parent
                    keys: ["text/uri-list", "text/plain"]
                    onDropped: (d) => {
                        if (root.isLinks) tools.addLinks(d.hasText ? d.text : d.urls.join("\n"))
                        else if (d.hasUrls) tools.addPaths(d.urls.map(u => u.toString()))
                    }
                }
            }

            }

            // ------------------------------------------------------------------ options
            Card {
                Layout.preferredWidth: 340
                Layout.minimumWidth: 300
                Layout.fillHeight: true

                Flickable {
                    anchors { left: parent.left; right: parent.right; top: parent.top; bottom: startBox.top; margins: 16 }
                    contentHeight: opts.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    ColumnLayout {
                        id: opts
                        width: parent.width
                        spacing: 16

                        // ---------- To MP3
                        Group {
                            visible: root.key === "mp3"
                            title: "Format"
                            note: ({ mp3: "Plays everywhere.", m4a: "AAC: smaller than MP3 at the same quality.", wav: "Uncompressed, big files. Quality doesn't apply.",
                                     flac: "Lossless and compressed. Quality doesn't apply.", opus: "Most efficient; not every player supports it." })[root.o.format] || ""
                            Seg { Layout.fillWidth: true; model: ["mp3", "m4a", "wav", "flac", "opus"].map(f => ({ value: f, label: f.toUpperCase() })); current: String(root.o.format); onPicked: (v) => tools.setOption("format", v) }
                        }
                        Group {
                            visible: root.key === "mp3"
                            title: "Quality"
                            opacity: (root.o.format === "wav" || root.o.format === "flac") ? 0.4 : 1
                            Seg { Layout.fillWidth: true; model: [128, 192, 256, 320].map(b => ({ value: b, label: b + "k", enabled: !(root.o.format === "wav" || root.o.format === "flac") })); current: String(root.o.bitrate); onPicked: (v) => tools.setOption("bitrate", v) }
                        }
                        Rectangle {  // the one that matters for beat-matching: shown prominently
                            visible: root.key === "mp3"
                            Layout.fillWidth: true
                            implicitHeight: trimRow.implicitHeight + 24
                            radius: 14
                            color: root.o.trim ? Theme.accSoft : Theme.card2A
                            border.width: 1
                            border.color: root.o.trim ? Theme.alpha(Theme.acc, 0.5) : Theme.line
                            Behavior on color { ColorAnimation { duration: 200 } }
                            Behavior on border.color { ColorAnimation { duration: 200 } }
                            ToggleRow {
                                id: trimRow
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                                title: "Start at the real start of the song"
                                checked: !!root.o.trim
                                onToggled: (v) => tools.setOption("trim", v)
                            }
                        }
                        ToggleRow { visible: root.key === "mp3"; title: "Add cover art"; sub: "Embeds the thumbnail as album art"; checked: !!root.o.cover; onToggled: (v) => tools.setOption("cover", v) }
                        ToggleRow { visible: root.key === "mp3"; title: "Add title and artist tags"; checked: !!root.o.tags; onToggled: (v) => tools.setOption("tags", v) }

                        // ---------- Convert
                        Group {
                            visible: root.key === "convert"
                            title: "Video and audio to"
                            Flow {
                                Layout.fillWidth: true
                                spacing: 6
                                Repeater {
                                    model: ["mp4", "mkv", "webm", "mov", "avi", "gif", "mp3", "m4a", "wav", "flac", "ogg", "opus"]
                                    delegate: Rectangle {
                                        required property string modelData
                                        readonly property bool on: root.o.format === modelData
                                        width: 48; height: 30; radius: 9
                                        color: on ? Theme.acc : Theme.card2A
                                        border.width: on ? 0 : 1; border.color: Theme.line
                                        Behavior on color { ColorAnimation { duration: 180 } }
                                        scale: cma.pressed ? 0.94 : 1
                                        Behavior on scale { SpringAnimation { spring: 5; damping: 0.4; epsilon: 0.002 } }
                                        Text { anchors.centerIn: parent; text: modelData.toUpperCase(); color: parent.on ? Theme.accText : Theme.t2; font.family: Theme.fontUi; font.pixelSize: 11; font.weight: Font.DemiBold }
                                        MouseArea { id: cma; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: tools.setOption("format", modelData) }
                                    }
                                }
                            }
                        }
                        Group {
                            visible: root.key === "convert" && root.videoFormats.indexOf(root.o.format) >= 0
                            title: "Resolution"
                            Seg { Layout.fillWidth: true; model: [{ value: "src", label: "Source" }, { value: "1080", label: "1080p" }, { value: "720", label: "720p" }, { value: "480", label: "480p" }]; current: String(root.o.resolution); onPicked: (v) => tools.setOption("resolution", v) }
                        }
                        Group {
                            visible: root.key === "convert" && root.videoFormats.indexOf(root.o.format) >= 0
                            title: "Quality " + root.o.quality + "%"
                            AppSlider { Layout.fillWidth: true; from: 10; to: 100; step: 5; value: root.o.quality || 0; label: "Quality"; onMoved: (v) => tools.setOption("quality", v) }
                        }
                        Group {
                            visible: root.key === "convert" && ["wav", "flac", "gif"].indexOf(root.o.format) < 0
                            title: "Audio bitrate"
                            Seg { Layout.fillWidth: true; model: [128, 192, 256, 320].map(b => ({ value: b, label: b + "k" })); current: String(root.o.abr); onPicked: (v) => tools.setOption("abr", v) }
                        }
                        Rectangle { visible: root.key === "convert"; Layout.fillWidth: true; height: 1; color: Theme.line }
                        Group {
                            visible: root.key === "convert"
                            title: "Pictures to"
                            Seg { Layout.fillWidth: true; model: ["png", "jpg", "webp", "bmp", "tiff"].map(f => ({ value: f, label: f.toUpperCase() })); current: String(root.o.img_format); onPicked: (v) => tools.setOption("img_format", v) }
                        }
                        Group {
                            visible: root.key === "convert" && ["jpg", "webp"].indexOf(root.o.img_format) >= 0
                            title: "Picture quality " + root.o.img_quality + "%"
                            AppSlider { Layout.fillWidth: true; from: 30; to: 100; step: 5; value: root.o.img_quality || 0; label: "Picture quality"; onMoved: (v) => tools.setOption("img_quality", v) }
                        }
                        ToggleRow { visible: root.key === "convert"; title: "Keep photo info (EXIF)"; sub: "Camera, date and location. Off removes it."; checked: !!root.o.meta; onToggled: (v) => tools.setOption("meta", v) }

                        // ---------- Resize
                        Group {
                            visible: root.key === "resize"
                            title: "Resize by"
                            note: ({ percent: "Scale every picture by the same amount.", fit: "Shrink to fit inside the box. Proportions are kept.",
                                     exact: "Set an exact width and height.", crop: "Fill the exact size, cropping the edges (good for thumbnails)." })[root.o.mode] || ""
                            Seg { Layout.fillWidth: true; model: [{ value: "percent", label: "Percent" }, { value: "fit", label: "Fit" }, { value: "exact", label: "Exact" }, { value: "crop", label: "Crop" }]; current: String(root.o.mode); onPicked: (v) => tools.setOption("mode", v) }
                        }
                        Group {
                            visible: root.key === "resize" && root.o.mode === "percent"
                            title: "Scale " + root.o.percent + "%"
                            AppSlider { Layout.fillWidth: true; from: 5; to: 200; step: 5; value: root.o.percent || 0; label: "Scale"; onMoved: (v) => tools.setOption("percent", v) }
                        }
                        Group {
                            visible: root.key === "resize" && root.o.mode !== "percent"
                            title: "Size in pixels"
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                FieldBox { Layout.fillWidth: true; mono: true; suffix: "W"; text: String(root.o.width); onEdited: (t) => { const n = parseInt(t); if (n > 0) tools.setOption("width", n) } }
                                Text { text: "×"; color: Theme.t3; font.pixelSize: 14 }
                                FieldBox { Layout.fillWidth: true; mono: true; suffix: "H"; text: String(root.o.height); onEdited: (t) => { const n = parseInt(t); if (n > 0) tools.setOption("height", n) } }
                            }
                        }
                        ToggleRow { visible: root.key === "resize" && root.o.mode === "exact"; title: "Keep proportions"; sub: "Changing one side sets the other from the picture"; checked: !!root.o.keep_aspect; onToggled: (v) => tools.setOption("keep_aspect", v) }
                        Group {
                            visible: root.key === "resize"
                            title: "Save as"
                            Seg { Layout.fillWidth: true; model: [{ value: "same", label: "Same" }, { value: "png", label: "PNG" }, { value: "jpg", label: "JPG" }, { value: "webp", label: "WebP" }]; current: String(root.o.format); onPicked: (v) => tools.setOption("format", v) }
                        }
                        Group {
                            visible: root.key === "resize"
                            title: "File name ending"
                            FieldBox { Layout.fillWidth: true; mono: true; text: String(root.o.suffix); onEdited: (t) => tools.setOption("suffix", t) }
                        }

                        // ---------- Compress
                        Group {
                            visible: root.key === "compress"
                            title: "How much"
                            note: ({ light: "Barely visible changes. PDF images at 200 dpi, photos at quality 85, video CRF 26.",
                                     balanced: "Good for sharing. PDF images at 150 dpi, photos up to 2560 px, video up to 1080p.",
                                     strong: "Smallest files. PDF images at 100 dpi, photos up to 1600 px, video up to 720p." })[root.o.level] || ""
                            Seg { Layout.fillWidth: true; model: [{ value: "light", label: "Light" }, { value: "balanced", label: "Balanced" }, { value: "strong", label: "Strong" }]; current: String(root.o.level); onPicked: (v) => tools.setOption("level", v) }
                        }

                        // ---------- where to save (everything)
                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
                        ToggleRow { visible: !root.isLinks; title: "Save next to the originals"; checked: tools.toOriginals; onToggled: (v) => tools.setToOriginals(v) }
                        Group {
                            visible: root.isLinks || !tools.toOriginals
                            title: "Save to"
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Text { Layout.fillWidth: true; text: tools.folder; elide: Text.ElideMiddle; color: Theme.t2; font.family: Theme.fontMono; font.pixelSize: 11 }
                                Btn { compact: true; text: "Change"; onClicked: tools.chooseFolder() }
                            }
                        }
                        Item { Layout.preferredHeight: 4 }
                    }
                }

                // start / cancel
                ColumnLayout {
                    id: startBox
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 16 }
                    spacing: 8
                    Btn {
                        Layout.fillWidth: true
                        visible: !tools.running
                        primary: true
                        text: tools.startLabel + (tools.pendingCount > 1 ? " (" + tools.pendingCount + ")" : "")
                        iconPath: Icons.download
                        isEnabled: tools.canStart
                        onClicked: tools.start()
                    }
                    Btn {
                        Layout.fillWidth: true
                        visible: tools.running
                        danger: true
                        text: "Stop"
                        onClicked: tools.cancel()
                    }
                    Text {
                        visible: tools.busyElsewhere
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: "Another session is still working."
                        color: Theme.t3; font.family: Theme.fontUi; font.pixelSize: 11
                    }
                }
            }
        }
    }
}
