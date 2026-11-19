"""M6 前置：live 实时副官 + launcher + paths 单元测试."""
from __future__ import annotations

import numpy as np

from tft_copilot.live import LiveCopilot, load_anchors_config
from tft_copilot.paths import is_frozen, writable_data_dir
from tft_copilot.perception.scene import GameScene
from tft_copilot.perception.synth import synth_scene_frame


def test_paths_source_mode():
    assert not is_frozen()
    d = writable_data_dir()
    assert d.name == "data"
    assert (d / "units" / "units_18.6.json").is_file()


def test_patch_data_paths_frozen_simulated(tmp_path, monkeypatch):
    import tft_copilot.paths as paths_mod
    import tft_copilot.perception.units_spotter as spotter
    import tft_copilot.replay_cli as replay_cli

    monkeypatch.setattr(paths_mod, "is_frozen", lambda: True)
    monkeypatch.setattr(paths_mod, "exe_dir", lambda: tmp_path)
    wroot = paths_mod.patch_data_paths()
    assert wroot == tmp_path / "writable_data"
    assert replay_cli.DEFAULT_DB == str(wroot / "db" / "matches_v18.6.db")
    assert spotter.PENDING_DIR == wroot / "pending_templates"


def test_load_anchors_config():
    cfg = load_anchors_config()
    assert set(cfg["numbers"].keys()) == {"layer", "gold", "hp", "level"}
    assert len(cfg["units"]["shop5"]["rois"]) == 5


class GrabberStub:
    def __init__(self, frames):
        self._frames = frames

    def grab(self):
        return self._frames.pop(0)


class SchedulerStub:
    def __init__(self, scenes, interval=0.01):
        self._scenes = scenes
        self._interval = interval

    def detect(self, frame):
        return self._scenes.pop(0)

    def poll_interval(self, scene):
        return self._interval


class SpotterStub:
    def spot(self, frame, area):
        return []


def test_shop_frame_feeds_engine(tmp_path):
    db = tmp_path / "m.db"
    lc = LiveCopilot(db_path=db, quiet=True)
    frame = synth_scene_frame("shop", layer=12, gold=34, hp=87, level=7)
    lc._grabber = GrabberStub([frame])
    lc._scheduler = SchedulerStub([GameScene.SHOP])
    lc._spotter = SpotterStub()
    interval = lc._poll_once()
    assert interval == 0.01
    assert lc._round_no == 0
    assert lc._match_id is not None


def test_unknown_frame_skips_engine(tmp_path):
    db = tmp_path / "m.db"
    lc = LiveCopilot(db_path=db, quiet=True)
    lc._grabber = GrabberStub([np.zeros((1080, 1920, 3), dtype=np.uint8)])
    lc._scheduler = SchedulerStub([GameScene.UNKNOWN], interval=1.0)
    assert lc._poll_once() == 1.0
    assert lc._match_id is None


def test_battle_round_increment(tmp_path):
    db = tmp_path / "m.db"
    lc = LiveCopilot(db_path=db, quiet=True)
    frame = synth_scene_frame("battle")
    lc._grabber = GrabberStub([frame])
    lc._scheduler = SchedulerStub([GameScene.BATTLE])
    lc._spotter = SpotterStub()
    lc._poll_once()
    assert lc._round_no == 1


def test_max_seconds_exit(tmp_path):
    db = tmp_path / "m.db"
    lc = LiveCopilot(db_path=db, quiet=True)
    frames = [np.zeros((1080, 1920, 3), dtype=np.uint8)] * 500
    lc._grabber = GrabberStub(frames)
    lc._scheduler = SchedulerStub([GameScene.UNKNOWN] * 500, interval=0.05)
    stats = lc.start_live(max_seconds=0.3)
    assert stats["frames"] >= 1
    assert stats["duration"] >= 0.3
