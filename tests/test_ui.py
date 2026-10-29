"""UI state tests (pytest-qt, offscreen)."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipdl.core import settings  # noqa: E402
from clipdl.core.media_info import VideoInfo  # noqa: E402


@pytest.fixture
def app_win(qtbot, tmp_path):
    from clipdl.controller import AppController
    from clipdl.ui import theme
    from clipdl.ui.main_window import MainWindow
    theme.load_fonts()
    win = MainWindow()
    qtbot.addWidget(win)
    ctl = AppController(win, settings.AppSettings(save_folder=str(tmp_path), glass=False),
                        settings_path=tmp_path / "s.json")
    win.show()
    return win, ctl


def fake_info(duration=120.0):
    return VideoInfo(id="x", title='Bad: "name" / test?', channel="C", duration=duration, thumbnail=None,
                     webpage_url="", heights=[360, 720, 1080], max_height=1080, fps=30.0,
                     preview_video=None, preview_audio=None, waveform_audio=None)


def load(ctl, info=None, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"):
    from clipdl.controller import State
    ctl.url = url
    ctl.token += 1
    ctl.set_state(State.LOADING)
    ctl._on_info((str(ctl.token), info or fake_info()))


def test_starts_empty(app_win):
    win, ctl = app_win
    assert ctl.state == "empty"
    assert win.left.currentWidget() is win.empty_view
    assert not win.export.download_btn.isEnabled()


def test_invalid_url(app_win):
    win, ctl = app_win
    ctl.load_url("https://vimeo.com/1")
    assert ctl.state == "empty"
    assert win.url_bar.box.property("invalid") is True
    assert "YouTube" in win.empty_view.error.text()


def test_info_sets_defaults(app_win):
    win, ctl = app_win
    load(ctl, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=40")
    assert ctl.state == "ready"
    assert (ctl.start, ctl.end) == (40.0, 70.0)
    assert win.export.file_name() == "Bad name test"
    assert win.start_field.edit.text() == "0:40" and win.end_field.edit.text() == "1:10"


def test_range_rules(app_win):
    win, ctl = app_win
    load(ctl)
    ctl._set_start(200)  # beyond end -> clamped below end
    assert ctl.start == pytest.approx(ctl.end - 0.2)
    ctl._set_end(999)
    assert ctl.end == 120.0
    ctl._set_start(-5)
    assert ctl.start == 0.0
    win.start_field._on_text("1:30.5")
    assert ctl.start == 90.5
    win.end_field._on_text("abc")
    assert win.end_field.box.property("invalid") is True


def test_output_rules(app_win):
    win, ctl = app_win
    load(ctl)
    e = win.export
    e._on_format("mp3")
    assert not e.g_res.isEnabled() and not e.g_fps.isEnabled() and e.abr_seg.isEnabled()
    e._on_format("gif")
    o = e.output()
    assert o.audio is False and o.fps == 15 and o.resolution == 480
    assert not e.g_codec.isEnabled() and not e.audio_toggle.isEnabled()
    e._on_format("webm")
    assert e.output().codec == "vp9"
    assert not e.codec_seg._buttons["h264"].isEnabled()
    assert ctl.cfg.output.format == "webm"  # saved to settings


def test_resolution_options_follow_source(app_win):
    win, ctl = app_win
    load(ctl, info=VideoInfo(id="y", title="t", channel="", duration=60, thumbnail=None, webpage_url="",
                             heights=[360, 480], max_height=480, fps=30, ))
    seg = win.export.res_seg
    assert not seg._buttons[1080].isEnabled() and not seg._buttons[720].isEnabled()
    assert seg._buttons[360].isEnabled()


def test_clear_returns_to_empty(app_win):
    win, ctl = app_win
    load(ctl)
    ctl.clear()
    assert ctl.state == "empty" and ctl.info is None


def test_progress_and_done_states(app_win, tmp_path):
    from clipdl.core.clipper import ClipResult, Progress
    win, ctl = app_win
    load(ctl)
    ctl.set_state("downloading")
    ctl._on_progress(Progress("downloading", 42.0, 2_000_000, 8_000_000, speed_x=1.8, eta_s=3, elapsed_s=2))
    assert win.progress.ring._target == 42.0 and win.progress.ring._mode == "progress"
    assert win.trim.locked and win.trim.sweep == pytest.approx(0.42)
    f = tmp_path / "x.mp4"
    f.write_bytes(b"0" * 1000)
    ctl._on_done(("t", ClipResult(str(f), 1000, 3.0, False, ["MP4", "1080p"])))
    assert ctl.state == "done" and win.side_stack.currentWidget() is win.done
    assert not win.trim.locked and win.trim.sweep is None


def test_settings_saved(app_win, tmp_path):
    win, ctl = app_win
    load(ctl)
    win.export._set(fps=24)
    ctl.save_settings()
    assert settings.load(tmp_path / "s.json").output.fps == 24


def test_player_plays_whole_video_outside_clip(app_win):
    """Regression: with Loop on, playing outside the clip used to snap back to the clip start."""
    win, ctl = app_win
    load(ctl)
    p = win.player
    p.set_clip(10, 20)
    p.set_loop(True)
    p._playing = True
    # playing after the clip keeps going
    p._pos = 30.0
    p._on_pos(30100)
    assert p.position() == pytest.approx(30.1)
    # playing before the clip runs into and through... the clip start
    p._pos = 5.0
    p._on_pos(5100)
    assert p.position() == pytest.approx(5.1)
    # inside the clip, reaching the end wraps to the start when Loop is on
    p._pos = 19.95
    p._on_pos(20000)
    assert p.position() == pytest.approx(10.0)
    # with Loop off it carries on past the end
    p.set_loop(False)
    p._pos = 19.95
    p._on_pos(20000)
    assert p.position() == pytest.approx(20.0)
    p._playing = False


def test_play_does_not_jump_to_clip(app_win):
    win, ctl = app_win
    load(ctl)
    p = win.player
    p.set_clip(10, 20)
    p.set_loop(True)
    p.seek_to(45.0)
    p.play()  # no source in tests -> returns early; position must be untouched
    assert p.position() == pytest.approx(45.0)


def test_loop_off_by_default():
    assert settings.AppSettings().loop is False


def test_sessions_switch_in_one_window(qtbot, tmp_path):
    from clipdl.app import AppContext
    from clipdl.controller import AppController
    from clipdl.ui import theme
    from clipdl.ui.main_window import MainWindow
    theme.load_fonts()
    cfg = settings.AppSettings(save_folder=str(tmp_path), appearance="solid")
    ctx = AppContext(cfg, tmp_path / "s.json")
    win = MainWindow()
    qtbot.addWidget(win)
    ctx.main = win
    ctl = AppController(win, cfg, settings_path=tmp_path / "s.json")
    win.sessionRequested.connect(ctx.switch_session)
    win.show()
    assert win.current_session() == "clip"
    for key in ("audio", "convert", "resize", "compress"):
        win.switcher.actions_by_key[key].trigger()
        assert win.current_session() == key
        assert win.pages.currentWidget() is ctx.tools[key]
        assert win.switcher.text().strip().startswith(win.switcher.info[key][0])
    # pages are kept, not recreated
    page = ctx.tools["convert"]
    ctx.switch_session("clip")
    ctx.switch_session("convert")
    assert ctx.tools["convert"] is page
    assert cfg.tools["_app"]["session"] == "convert"
    # video shortcuts are ignored outside the Clip Video session
    ctl.set_state("ready")
    before = ctl.state
    win.player.toggle  # noqa: B018
    assert win.current_session() == "convert" and ctl.state == before
    assert ctx.can_close()
    # the old Images session opens the combined converter
    ctx.switch_session("images")
    assert win.current_session() == "convert"
