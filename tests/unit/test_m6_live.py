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


class _Advice:
    def __init__(self, level, text):
        self.level = level
        self.text = text


def test_console_prints_only_on_change(tmp_path, capsys):
    """v3 降噪：读数不变不重印；建议同文本一局只报一次。"""
    db = tmp_path / "m.db"
    lc = LiveCopilot(db_path=db, quiet=False)
    nums = {"layer": 8, "gold": 2, "hp": 90, "level": 1, "stage_major": 1, "stage_minor": 1}
    adv = [_Advice("info", "下一档：10 层，还差 2 层")]
    # 同读数同建议连打 3 次：只应出现 1 次读数行 + 1 次建议
    for _ in range(3):
        lc._push_hud(nums, adv)
    out1 = capsys.readouterr().out
    assert out1.count("层8") == 1
    assert out1.count("下一档") == 1
    # 读数变化：新读数行出现；建议重复不重报
    nums2 = {**nums, "gold": 10}
    lc._push_hud(nums2, adv)
    out2 = capsys.readouterr().out
    assert out2.count("金10") == 1
    assert "下一档" not in out2


def test_idle_hint_prints_once_until_change(tmp_path, capsys):
    """v3 降噪：空闲提示同文本只打一次，变化才重打。"""
    db = tmp_path / "m.db"
    lc = LiveCopilot(db_path=db, quiet=False)
    for _ in range(3):
        lc._idle_hint(GameScene.UNKNOWN)
    out1 = capsys.readouterr().out
    assert out1.count("等待对局") == 1
    lc._idle_hint(GameScene.PRE_GAME)
    out2 = capsys.readouterr().out
    assert out2.count("游戏大厅") == 1


def test_streak_settles_on_round_boundary(tmp_path):
    """v4 连胜/连败：回合边界结算，血不变=胜、下降=败、转胜归 1。"""
    db = tmp_path / "m.db"
    lc = LiveCopilot(db_path=db, quiet=True)
    lc._last_scene = GameScene.SHOP
    seq = [(100, 0), (100, 1), (100, 2), (95, -1), (88, -2), (88, 1)]
    for hp, want in seq:
        lc._maybe_new_round(GameScene.BATTLE, {"hp": hp})
        assert lc._streak == want, f"hp={hp} streak={lc._streak} want={want}"
        lc._last_scene = GameScene.SHOP  # 手动重置供下一次边界


def test_streak_income_advice():
    """v4 收入预估：连X奖励+利息算进下回合收入。"""
    from tft_copilot.decision.strategy import streak_advice, streak_bonus
    assert streak_bonus(1) == 0
    assert streak_bonus(3) == 1
    assert streak_bonus(4) == 2
    assert streak_bonus(9) == 3
    a = streak_advice(46, 3)[0]
    assert "3连胜" in a.text and "=10" in a.text  # 5+1+4
    b = streak_advice(52, -4)[0]
    assert "4连败" in b.text and "=12" in b.text  # 5+2+5
    assert streak_advice(30, 0) == []
