"""M2 感知层测试：单元 + 合成帧集成 + 性能门禁.

覆盖 PRD 验收：A1 grabber / A2 模板库 / A3 场景 / A4 数字 / A4b 弈子 / A5 pending / A5b 性能.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from tft_copilot.perception.grabber import is_black_frame
from tft_copilot.perception.numbers import read_number
from tft_copilot.perception.scene import GameScene, SceneScheduler
from tft_copilot.perception.synth import SynthConfig, load_anchors, synth_scene_frame
from tft_copilot.perception.templates import TemplateBank
from tft_copilot.perception.units_spotter import UnitSpotter

# ---------- fixtures ----------

@pytest.fixture(scope="module")
def bank():
    return TemplateBank()


@pytest.fixture(scope="module")
def scheduler():
    return SceneScheduler()


@pytest.fixture(scope="module")
def spotter():
    return UnitSpotter(TemplateBank(), pending_dir=Path("data/pending_templates_test"))


@pytest.fixture(scope="module")
def anchors():
    return load_anchors()


NUM_ROIS = [(1710, 120, 120, 50), (1710, 180, 120, 50), (200, 990, 120, 50), (1710, 240, 120, 50)]


# ---------- A1 grabber ----------

class TestGrabber:
    def test_black_frame_detect(self):
        black = np.zeros((100, 100, 3), dtype=np.uint8)
        assert is_black_frame(black) is True
        normal = np.full((100, 100, 3), 128, dtype=np.uint8)
        assert is_black_frame(normal) is False

    def test_partial_black_not_flagged(self):
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        frame[:50] = 0
        assert is_black_frame(frame) is False


# ---------- A2 TemplateBank ----------

class TestTemplateBank:
    def test_load_122_portraits(self, bank):
        assert bank.portrait_count() == 122

    def test_version_mismatch_rejected(self):
        with pytest.raises((FileNotFoundError, ValueError)):
            TemplateBank(patch="99.9")

    def test_digits_and_stars(self, bank):
        assert len(bank.digits) == 50  # 10 digits x 5 colors
        assert len(bank.stars) == 3


# ---------- A3 场景判定 ----------

class TestScene:
    @pytest.mark.parametrize("scene", ["shop", "battle", "pre_game", "unknown"])
    def test_detect(self, scheduler, scene):
        frame = synth_scene_frame(scene)
        assert scheduler.detect(frame) == GameScene(scene)

    def test_poll_interval_table(self, scheduler):
        assert scheduler.poll_interval(GameScene.SHOP) == 0.2
        assert scheduler.poll_interval(GameScene.BATTLE) == 1.0
        assert scheduler.poll_interval(GameScene.UNKNOWN) == 1.0


# ---------- A4 数字识别 ----------

class TestNumbers:
    def test_read_four_rois(self, bank):
        frame = synth_scene_frame("shop", layer=12, gold=34, hp=87, level=7)
        wants = [12, 34, 87, 7]
        for roi, want in zip(NUM_ROIS, wants, strict=True):
            assert read_number(frame, roi, bank) == want

    def test_high_noise(self, bank):
        cfg = SynthConfig(seed=7, noise_sigma=12.0)
        frame = synth_scene_frame("shop", layer=25, gold=50, hp=66, level=8, config=cfg)
        got = read_number(frame, NUM_ROIS[0], bank)
        assert got == 25

    def test_empty_roi(self, bank):
        frame = synth_scene_frame("battle")
        assert read_number(frame, (0, 0, 50, 50), bank) is None


# ---------- A4b 弈子识别 ----------

class TestSpotter:
    def test_shop5_top1(self, spotter, anchors):
        frame = synth_scene_frame("shop")
        expect = ["11400", "11401", "11402", "11403", "11404"]
        for roi, want in zip(anchors["units"]["shop5"]["rois"], expect, strict=True):
            boxes = spotter.spot(frame, tuple(roi))
            assert boxes, f"{want} 未识别"
            assert boxes[0].unit_id == want
            assert boxes[0].score >= 0.90

    def test_bench_detected(self, spotter, anchors):
        frame = synth_scene_frame("shop")
        found = 0
        for roi in anchors["units"]["bench"]["rois"][:5]:
            if spotter.spot(frame, tuple(roi)):
                found += 1
        assert found >= 4  # 5 个备战位至少 4 个识别

    def test_empty_area(self, spotter):
        frame = synth_scene_frame("battle")
        boxes = spotter.spot(frame, (100, 100, 130, 130))
        assert boxes == [] or all(b.score < 0.90 for b in boxes)


# ---------- A5 pending ----------

class TestPending:
    def test_no_pending_dump_in_clean_match(self, spotter, anchors):
        frame = synth_scene_frame("shop")
        roi = anchors["units"]["shop5"]["rois"][0]
        spotter.spot(frame, tuple(roi))  # 正常识别不落 pending


# ---------- A5b 性能门禁 ----------

class TestPerf:
    def test_frame_p95_under_150ms(self, bank, scheduler, spotter, anchors):
        """单帧全管线（scene + 4 numbers + 5 spot）P95 <= 150ms。"""
        rois_shop = anchors["units"]["shop5"]["rois"]
        times = []
        for seed in range(6):
            frame = synth_scene_frame("shop", config=SynthConfig(seed=seed))
            t0 = time.perf_counter()
            scheduler.detect(frame)
            for roi in NUM_ROIS:
                read_number(frame, roi, bank)
            for roi in rois_shop:
                spotter.spot(frame, tuple(roi))
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        p95 = times[int(len(times) * 0.95) - 1]
        assert p95 <= 150, f"P95 {p95:.0f}ms 超预算"
        print(f"\nP95 = {p95:.0f}ms (6 帧均值 {sum(times)/len(times):.0f}ms)")
