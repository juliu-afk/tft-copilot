"""M3 决策层测试：快照/层数/战力/对位/推演（技术方案 §11）。"""

from __future__ import annotations

import pytest

from tft_copilot.decision.impact import evaluate as impact_eval
from tft_copilot.decision.layer_progress import LayerProgress, build_rewards_map
from tft_copilot.decision.matchup import advice_for, predict
from tft_copilot.decision.power_score import PowerScorer
from tft_copilot.decision.snapshot import (
    BoardSnapshot,
    LayersGuard,
    PlayerState,
    TaskState,
    UnitOnBoard,
    quality_gate,
)
from tft_copilot.knowledge.rules_loader import load_rules
from tft_copilot.knowledge.units_loader import UnitsBook


@pytest.fixture(scope="module")
def book():
    return UnitsBook.from_file("data/units/units_18.6.json")


@pytest.fixture(scope="module")
def rules():
    return load_rules()


# ---------- 快照与卫兵 ----------

class TestLayersGuard:
    def test_first_frame_accepted(self):
        g = LayersGuard()
        assert g.track(300) == 300

    def test_monotonic_increase_accepted(self):
        g = LayersGuard()
        g.track(100)
        assert g.track(150) == 150
        assert g.track(250) == 250

    def test_negative_jump_rejected(self):
        g = LayersGuard()
        g.track(300)
        assert g.track(30) is None  # 负跳变丢弃

    def test_huge_jump_rejected(self):
        g = LayersGuard()
        g.track(100)
        assert g.track(250) is None  # 跳变 150 > 100 丢弃

    def test_boundary_jump_100_accepted(self):
        g = LayersGuard()
        g.track(100)
        assert g.track(200) == 200  # 恰好 100 合法

    def test_none_passthrough(self):
        assert LayersGuard().track(None) is None


class TestQualityGate:
    def test_below_th_silent(self):
        assert quality_gate(0.29) is False

    def test_at_th_pass(self):
        assert quality_gate(0.3) is True

    def test_normal_pass(self):
        assert quality_gate(0.95) is True


class TestTrustedUnits:
    def test_pending_filtered(self):
        snap = BoardSnapshot(
            round_no=1, scene="shop", quality=0.9,
            my_units=[
                UnitOnBoard("a", 1, 1, 0.99),
                UnitOnBoard("b", 1, 1, 0.44),  # pending 剔除
                UnitOnBoard("c", 1, 1, 0.45),  # 恰好阈值保留
            ],
            layers=10, hp=80, gold=50, level=8,
        )
        ids = [u.unit_id for u in snap.trusted_units()]
        assert ids == ["a", "c"]


# ---------- 模块(1) 层数进度 ----------

class TestLayerProgress:
    RW = {500: "4金币 / 二费卡x2", 100: "10碎片"}

    def test_milestone_pre_alert(self):
        lp = LayerProgress(self.RW)
        advs = lp.on_layers(99, 80)
        assert any("还差 1 层" in a.text and "10碎片" in a.text for a in advs)

    def test_milestone_hit_alert(self):
        lp = LayerProgress(self.RW)
        advs = lp.on_layers(100, 80)
        assert any("达成 100 层档" in a.text for a in advs)

    def test_once_dedup(self):
        lp = LayerProgress(self.RW)
        lp.on_layers(99, 80)
        advs = lp.on_layers(99, 80)  # 同层重复帧
        assert not any("还差 1 层" in a.text for a in advs)

    def test_stop_rule(self):
        lp = LayerProgress(self.RW)
        advs = lp.on_layers(500, 35)
        assert any(a.level == "critical" and "达标即停" in a.text for a in advs)

    def test_stop_rule_hp_none_no_fire(self):
        lp = LayerProgress(self.RW)
        advs = lp.on_layers(500, None)
        assert not any("达标即停" in a.text for a in advs)

    def test_stop_not_triggered_when_hp_healthy(self):
        lp = LayerProgress(self.RW)
        advs = lp.on_layers(500, 80)
        assert not any("达标即停" in a.text for a in advs)

    def test_layers_none_no_output(self):
        assert LayerProgress(self.RW).on_layers(None, 80) == []

    def test_build_rewards_map(self, rules):
        m = build_rewards_map(rules.rewards)
        assert 500 in m
        assert "金币" in m[500] or "碎片" in m[500] or len(m[500]) > 0


# ---------- 模块(2) 战力评分 ----------

class TestPowerScorer:
    def test_unknown_player_none(self, book):
        sc = PowerScorer(book)
        assert sc.score(PlayerState("p1", None, None)) is None

    def test_empty_units_zero_star(self, book):
        sc = PowerScorer(book)
        s = sc.score(PlayerState("me", [], 80, []))
        assert s is not None and 0 <= s <= 100

    def test_star_gradient(self, book):
        """三星阵容战力分必须高于一星同配置。"""
        sc = PowerScorer(book)
        ids = [u.id for u in book][:10]
        lo = PlayerState("me", [UnitOnBoard(i, 1, 1, 0.99) for i in ids], 80, [80] * 5)
        hi = PlayerState("me", [UnitOnBoard(i, 1, 3, 0.99) for i in ids], 80, [80] * 5)
        assert sc.score(hi) > sc.score(lo)

    def test_star_none_as_one(self, book):
        """star=None 按一星基线：与显式一星同分（E4）。"""
        sc = PowerScorer(book)
        ids = [u.id for u in book][:5]
        a = PlayerState("me", [UnitOnBoard(i, 1, None, 0.99) for i in ids], 80, [80] * 5)
        b = PlayerState("me", [UnitOnBoard(i, 1, 1, 0.99) for i in ids], 80, [80] * 5)
        assert sc.score(a) == sc.score(b)

    def test_trend_penalty_on_bleeding(self, book):
        """掉血序列比稳血序列得分低。"""
        sc = PowerScorer(book)
        ids = [u.id for u in book][:8]
        stable = PlayerState("me", [UnitOnBoard(i, 1, 2, 0.99) for i in ids], 80, [80] * 5)
        bleed = PlayerState("me", [UnitOnBoard(i, 1, 2, 0.99) for i in ids], 30, [60, 52, 44, 37, 30])
        assert sc.score(bleed) < sc.score(stable)

    def test_pending_units_excluded(self, book):
        """低置信度弈子不参与评分。"""
        sc = PowerScorer(book)
        ids = [u.id for u in book][:5]
        with_pending = PlayerState(
            "me",
            [UnitOnBoard(i, 1, 1, 0.99) for i in ids] + [UnitOnBoard(ids[0], 1, 3, 0.30)],
            80, [80] * 5,
        )
        without = PlayerState("me", [UnitOnBoard(i, 1, 1, 0.99) for i in ids], 80, [80] * 5)
        assert sc.score(with_pending) == sc.score(without)

    def test_score_range(self, book):
        sc = PowerScorer(book)
        ids = [u.id for u in book][:10]
        s = sc.score(PlayerState("me", [UnitOnBoard(i, 1, 3, 0.99) for i in ids], 80, [80] * 5))
        assert 0 <= s <= 100

    def test_six_star_supported(self, book):
        """6 星体系不崩且分数高于三星（clamp 内单调）。"""
        sc = PowerScorer(book)
        ids = [u.id for u in book][:6]
        s3 = sc.score(PlayerState("me", [UnitOnBoard(i, 1, 3, 0.99) for i in ids], 80, [80] * 5))
        s6 = sc.score(PlayerState("me", [UnitOnBoard(i, 1, 6, 0.99) for i in ids], 80, [80] * 5))
        assert s6 >= s3


# ---------- 模块(3) 对位预测 ----------

class TestMatchup:
    def test_even(self):
        p = predict(50, 50)
        assert p.winrate == 0.5 and p.tier == "even"

    def test_high_tier(self):
        p = predict(70, 20)
        assert p.tier == "high" and p.winrate >= 0.65

    def test_low_tier(self):
        p = predict(20, 70)
        assert p.tier == "low" and p.winrate <= 0.35

    def test_confidence_high(self):
        assert predict(70, 20).confidence == "high"

    def test_confidence_low_near_diff(self):
        assert predict(50, 45).confidence == "low"

    def test_unknown_when_missing(self):
        p = predict(None, 50)
        assert p.winrate is None and p.tier == "unknown"
        p2 = predict(50, None)
        assert p2.tier == "unknown"

    def test_wr_bounds(self):
        """胜率上下界压缩：不出现 0/1 极端值。"""
        assert predict(100, 0).winrate == 0.95
        assert predict(0, 100).winrate == 0.05

    def test_advice_low_tier_sell_blood(self):
        advs = advice_for(predict(20, 70), "p3")
        assert any("卖血" in a.text for a in advs)

    def test_advice_high_tier_aggressive(self):
        advs = advice_for(predict(80, 30), "p2")
        assert any("激进" in a.text for a in advs)

    def test_advice_even_silent(self):
        assert advice_for(predict(50, 50), "p1") == []


# ---------- 模块(4) 影响推演 ----------

class TestImpact:
    def test_win_streak_break_risk(self):
        advs = impact_eval(
            predict(20, 70), TaskState("win", 5), 100, 200, None
        )
        assert any("断连" in a.text and a.level == "warn" for a in advs)

    def test_lose_streak_break_alert(self):
        advs = impact_eval(
            predict(80, 30), TaskState("lose", 3), 100, 200, None
        )
        assert any("连败要断" in a.text and a.level == "critical" for a in advs)

    def test_lose_streak_win_low_tier(self):
        advs = impact_eval(
            predict(20, 70), TaskState("lose", 3), 100, 200, None
        )
        assert any("正合连败流" in a.text for a in advs)

    def test_fragment_hint_near_reward(self):
        advs = impact_eval(predict(50, 50), None, 95, 98, "2金币")
        assert any("还差 3 层" in a.text for a in advs)

    def test_fragment_hint_far_no_alert(self):
        advs = impact_eval(predict(50, 50), None, 100, 200, None)
        assert not any("还差" in a.text for a in advs)

    def test_task_none_degrades(self):
        """E5：无任务状态时只出层数路，不提任务。"""
        advs = impact_eval(predict(20, 70), None, 100, 200, None)
        assert not any("连胜" in a.text or "连败" in a.text for a in advs)
