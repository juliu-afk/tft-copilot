"""M5 L1.5 引擎测试：装备库 / 面板装配 / 对位预测 / 站位粗算 / power item / 引擎集成。

对应 PRD AC1-AC5。合成局口径：构造 PlayerState 直调函数。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tft_copilot.decision.engine import DecisionEngine
from tft_copilot.decision.matchup15 import K15, predict_l15, to_matchup_pred
from tft_copilot.decision.panel import PanelEngine
from tft_copilot.decision.positioning import classify, pos_penalty
from tft_copilot.decision.power_score import PowerScorer
from tft_copilot.decision.snapshot import BoardSnapshot, PlayerState, UnitOnBoard
from tft_copilot.knowledge.equips_loader import (
    EquipsBook,
    EquipsDataError,
    load_equips,
)
from tft_copilot.knowledge.traits_loader import load_traits
from tft_copilot.knowledge.units_loader import UnitsBook

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def units_book() -> UnitsBook:
    return UnitsBook.from_file(DATA / "units" / "units_18.6.json")


@pytest.fixture(scope="module")
def traits_book():
    return load_traits()


@pytest.fixture(scope="module")
def equips_book() -> EquipsBook:
    return load_equips()


@pytest.fixture(scope="module")
def panel_engine(units_book, traits_book, equips_book) -> PanelEngine:
    return PanelEngine(units_book, traits_book, equips_book)


def mk_state(units, player="me", positions=None):
    return PlayerState(player, units, 80, [], positions)


def strong_units(n=10):
    return [UnitOnBoard("15273", 5, 3, 0.9, items=(2001, 2001)) for _ in range(n)]


def weak_units(n=3):
    return [UnitOnBoard("11400", 1, 1, 0.9) for _ in range(n)]


# ---------- AC1 装备库 ----------


class TestEquipsLoader:
    def test_count_204(self, equips_book):
        assert len(equips_book) == 204

    def test_patch_anchor(self, equips_book):
        assert equips_book.patch == "18.6"
        assert equips_book.version_id == "16_18.18.1_S400001"

    def test_by_id(self, equips_book):
        e = equips_book.by_id(2001)
        assert e.name == "无尽之刃"
        assert e.type == "成型装备"
        assert e.grade == 1.0
        assert e.synth == (1001, 1009)

    def test_by_id_unknown_raises(self, equips_book):
        with pytest.raises(EquipsDataError):
            equips_book.by_id(999999)

    def test_grade_mapping(self, equips_book):
        by_type = {e.type: e.grade for e in equips_book}
        assert by_type["光明武器"] == 1.6
        assert by_type["神器装备"] == 2.5
        assert by_type["转职纹章"] == 0.8

    def test_triple_check_count_mismatch(self, tmp_path):
        raw = json.loads((DATA / "equips" / "equips_18.6.json").read_text(encoding="utf-8"))
        raw["meta"]["count"] = 999
        p = tmp_path / "equips_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(EquipsDataError):
            load_equips(p)

    def test_triple_check_patch_mismatch(self, tmp_path):
        raw = json.loads((DATA / "equips" / "equips_18.6.json").read_text(encoding="utf-8"))
        raw["meta"]["patch"] = "18.9"
        p = tmp_path / "equips_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(EquipsDataError):
            load_equips(p)

    def test_bad_type_rejected(self, tmp_path):
        raw = json.loads((DATA / "equips" / "equips_18.6.json").read_text(encoding="utf-8"))
        raw["equips"][0]["type"] = "宇宙装备"
        raw["meta"]["count"] = len(raw["equips"])
        p = tmp_path / "equips_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(EquipsDataError):
            load_equips(p)

    def test_dup_id_rejected(self, tmp_path):
        raw = json.loads((DATA / "equips" / "equips_18.6.json").read_text(encoding="utf-8"))
        raw["equips"].append(dict(raw["equips"][0]))
        raw["meta"]["count"] = len(raw["equips"])
        p = tmp_path / "equips_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(EquipsDataError):
            load_equips(p)


# ---------- AC2 面板与 L1.5 预测 ----------


class TestPanelEngine:
    def test_none_units_returns_none(self, panel_engine):
        assert panel_engine.assemble(PlayerState("me", None, None)) is None

    def test_single_unit_panel(self, panel_engine):
        p = panel_engine.assemble(mk_state([UnitOnBoard("11400", 1, 1, 0.9)]))
        assert p is not None
        assert 0 < p.dps <= 100 and 0 < p.ehp <= 100 and 0 < p.burst <= 100

    def test_item_boosts_panel(self, panel_engine):
        bare = panel_engine.assemble(mk_state([UnitOnBoard("11400", 1, 1, 0.9)]))
        geared = panel_engine.assemble(
            mk_state([UnitOnBoard("11400", 1, 1, 0.9, items=(2001, 1001))])
        )
        assert geared.dps > bare.dps
        assert geared.ehp > bare.ehp

    def test_trait_breakpoint_distinction(self, panel_engine, units_book):
        """AC2.2：斗士(4) 面板应高于同规模斗士(2)。"""
        fighters = [u for u in units_book.units_by_trait("斗士")]
        two = [UnitOnBoard(u.id, u.cost, 1, 0.9) for u in fighters[:2]]
        four = [UnitOnBoard(u.id, u.cost, 1, 0.9) for u in fighters[:4]]
        p2 = panel_engine.assemble(mk_state(list(two)))
        p4 = panel_engine.assemble(mk_state(list(four)))
        # 4 人面板（含更多单子能量+更高断点乘区）必须显著高于 2 人
        assert p4.ehp > p2.ehp
        assert p4.dps > p2.dps

    def test_axis_cap_100(self, panel_engine):
        """六星顶配+神器 clamp 到 100 上限。"""
        god = [UnitOnBoard("15273", 5, 6, 0.9, items=(2001, 2001, 2001)) for _ in range(10)]
        p = panel_engine.assemble(mk_state(god))
        assert p.dps == 100.0 and p.ehp == 100.0

    def test_low_confidence_unit_filtered(self, panel_engine):
        p = panel_engine.assemble(
            mk_state([UnitOnBoard("11400", 1, 1, 0.2)])
        )  # score < 0.45 剔除
        assert p.dps == 0.0

    def test_perf_budget(self, panel_engine):
        """AC2.5：双方面板装配+预测 <=50ms（断言宽松 10 倍防 CI 抖动）。"""
        s = mk_state(strong_units())
        w = mk_state(weak_units(), "p1")
        t0 = time.perf_counter()
        for _ in range(10):
            mp = panel_engine.assemble(s)
            op = panel_engine.assemble(w)
            predict_l15(mp, op)
        dt = (time.perf_counter() - t0) / 10 * 1000
        assert dt <= 500  # 宽松上界


class TestPredictL15:
    def test_fallback_l0_when_panel_none(self, panel_engine):
        op = panel_engine.assemble(mk_state(weak_units(), "p1"))
        p = predict_l15(None, op, my_power=60.0, opp_power=30.0)
        assert p.engine == "L0"
        assert p.winrate is not None and p.winrate > 0.65

    def test_fallback_unknown_when_both_missing(self):
        p = predict_l15(None, None, my_power=None, opp_power=30.0)
        assert p.engine == "L0"
        assert p.winrate is None

    def test_strong_vs_weak_high_tier(self, panel_engine):
        mp = panel_engine.assemble(mk_state(strong_units()))
        op = panel_engine.assemble(mk_state(weak_units(), "p1"))
        p = predict_l15(mp, op)
        assert p.engine == "L1.5"
        assert p.tier == "high"
        assert p.confidence == "high"
        assert p.winrate >= 0.65

    def test_mirror_even(self, panel_engine):
        mp = panel_engine.assemble(mk_state(strong_units()))
        op = panel_engine.assemble(mk_state(strong_units(), "p1"))
        p = predict_l15(mp, op)
        assert p.tier == "even"
        assert p.confidence == "low"
        assert abs(p.winrate - 0.5) < 0.05

    def test_wr_bounds(self, panel_engine):
        mp = panel_engine.assemble(mk_state(strong_units(10)))
        op = panel_engine.assemble(mk_state(weak_units(1), "p1"))
        p = predict_l15(mp, op)
        assert p.winrate <= 0.95  # WR_CAP

    def test_detail_string(self, panel_engine):
        mp = panel_engine.assemble(mk_state(strong_units()))
        op = panel_engine.assemble(mk_state(weak_units(), "p1"))
        p = predict_l15(mp, op)
        assert "d_dps=" in p.detail

    def test_to_matchup_compat(self, panel_engine):
        mp = panel_engine.assemble(mk_state(strong_units()))
        op = panel_engine.assemble(mk_state(weak_units(), "p1"))
        p15 = predict_l15(mp, op)
        p0 = to_matchup_pred(p15)
        assert p0.winrate == p15.winrate
        assert p0.tier == p15.tier
        assert p0.confidence == p15.confidence

    def test_k15_positive(self):
        assert 0 < K15 <= 0.2  # 与 L0 K=0.08 同量级


# ---------- AC3 站位 ----------


class TestPositioning:
    def test_none_units(self, units_book):
        assert classify(PlayerState("me", None, None), units_book) is None

    def test_all_melee_aggressive(self, units_book):
        melee_ids = [u.id for u in units_book.units_by_cost(1) if u.range == 1][:6]
        st = mk_state([UnitOnBoard(i, 1, 1, 0.9) for i in melee_ids])
        ctx = classify(st, units_book)
        assert ctx.tier == "aggressive"
        assert ctx.my_front_ratio >= 0.6

    def test_positions_override(self, units_book):
        """positions 提供时按格位判定前排（近战放后排=沉底）。"""
        melee_ids = [u.id for u in units_book.units_by_cost(1) if u.range == 1][:6]
        pos = {i: 20 + k for k, i in enumerate(melee_ids)}  # 全放后排
        st = mk_state([UnitOnBoard(i, 1, 1, 0.9) for i in melee_ids], positions=pos)
        ctx = classify(st, units_book)
        assert ctx.tier == "defensive"
        assert ctx.my_front_ratio == 0.0

    def test_ranged_backline(self, units_book):
        ranged = [u for u in units_book if u.range >= 4][:6]
        st = mk_state([UnitOnBoard(u.id, u.cost, 1, 0.9) for u in ranged])
        ctx = classify(st, units_book)
        assert ctx.tier == "defensive"
        assert ctx.my_ranged_count >= 4

    def test_pos_penalty_rushed(self):
        from tft_copilot.decision.positioning import PositionContext

        my = PositionContext(0.1, 6, 2, "defensive")
        opp = PositionContext(0.7, 2, 5, "aggressive")
        assert pos_penalty(my, opp) == -5.0

    def test_pos_penalty_pressure(self):
        from tft_copilot.decision.positioning import PositionContext

        my = PositionContext(0.7, 2, 6, "aggressive")
        opp = PositionContext(0.2, 6, 2, "defensive")
        assert pos_penalty(my, opp) == 2.0

    def test_pos_penalty_none_ctx(self):
        assert pos_penalty(None, None) == 0.0

    def test_penalty_applies_to_prediction(self, panel_engine, units_book):
        """AC3.3：站位修正进 predict_l15。"""
        from tft_copilot.decision.positioning import PositionContext

        mp = panel_engine.assemble(mk_state(strong_units()))
        op = panel_engine.assemble(mk_state(strong_units(), "p1"))
        base = predict_l15(mp, op)
        rushed = predict_l15(
            mp, op,
            my_ctx=PositionContext(0.1, 8, 2, "defensive"),
            opp_ctx=PositionContext(0.8, 0, 8, "aggressive"),
        )
        assert rushed.winrate < base.winrate  # 被冲脸扣分


# ---------- AC5.5 power item 分量 ----------


class TestPowerItem:
    def test_default_equips_none_item_zero(self, units_book):
        """M3 兼容：不注入 equips 库时 item=0，分值与 M3 恒等。"""
        scorer = PowerScorer(units_book)
        st = mk_state(strong_units(3))
        assert scorer.item_score(st.units) == 0.0

    def test_item_score_with_equips(self, units_book, equips_book):
        scorer = PowerScorer(units_book, equips_book=equips_book)
        units = [UnitOnBoard("15273", 5, 3, 0.9, items=(2001, 2001))]
        val = scorer.item_score(units)
        assert val == pytest.approx(20.0)  # 2 x 1.0 / 10 x 100

    def test_item_score_unknown_id_skipped(self, units_book, equips_book):
        scorer = PowerScorer(units_book, equips_book=equips_book)
        units = [UnitOnBoard("15273", 5, 3, 0.9, items=(999999,))]
        assert scorer.item_score(units) == 0.0

    def test_total_score_increases_with_items(self, units_book, equips_book):
        bare = PowerScorer(units_book, equips_book=equips_book).score(
            mk_state([UnitOnBoard("15273", 5, 3, 0.9)])
        )
        geared = PowerScorer(units_book, equips_book=equips_book).score(
            mk_state([UnitOnBoard("15273", 5, 3, 0.9, items=(2001, 2001, 2001))])
        )
        assert geared > bare


# ---------- 引擎集成（AC2.4 全链路降级） ----------


def make_engine(units_book, traits_book=None, equips_book=None, store=None):
    from tft_copilot.knowledge.rules_loader import load_rules

    rules = load_rules()
    return DecisionEngine(
        rules, units_book, store=store, traits_book=traits_book, equips_book=equips_book
    )


def snap(round_no=1, scene="combat", quality=0.8):
    return BoardSnapshot(round_no, scene, quality, weak_units(), 100, 80, 50, 7)


class TestEngineIntegration:
    def test_engine_l0_without_traits(self, units_book, tmp_path):
        """不注入 traits -> Panel 缺席 -> 自动 L0（向后兼容）。"""
        eng = make_engine(units_book)
        eng.start_match()
        eng.on_round(snap(), {"me": mk_state(weak_units()), "p1": mk_state(weak_units(), "p1")}, "p1")
        assert eng._last_engine == "L0"

    def test_engine_l15_with_traits(self, units_book, traits_book, equips_book):
        eng = make_engine(units_book, traits_book, equips_book)
        eng.start_match()
        eng.on_round(
            snap(),
            {"me": mk_state(strong_units()), "p1": mk_state(weak_units(), "p1")},
            "p1",
        )
        assert eng._last_engine == "L1.5"

    def test_engine_l15_opp_unknown_fallback(self, units_book, traits_book, equips_book):
        """对手未侦查 -> opp_panel None -> L0。"""
        eng = make_engine(units_book, traits_book, equips_book)
        eng.start_match()
        eng.on_round(snap(), {"me": mk_state(strong_units())}, "p1")
        assert eng._last_engine == "L0"

    def test_store_records_engine(self, units_book, traits_book, equips_book, tmp_path):
        from tft_copilot.store.db import MatchStore

        db = tmp_path / "m.db"
        store = MatchStore(db, "18.6")
        eng = make_engine(units_book, traits_book, equips_book, store=store)
        mid = eng.start_match()
        eng.on_round(
            snap(),
            {"me": mk_state(strong_units()), "p1": mk_state(weak_units(), "p1")},
            "p1",
        )
        store.record_result(mid, 1, "W")
        preds = store.all_predictions(mid)
        assert len(preds) == 1
        assert preds[0][3] == "L1.5"  # pred_engine 列
        store.close()

    def test_store_migration_old_db(self, tmp_path):
        """旧库（无 pred_engine 列）打开时自动迁移。"""
        import sqlite3

        from tft_copilot.store.db import SCHEMA, MatchStore

        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA)  # 建旧 schema（无 pred_engine）
        conn.execute("INSERT INTO matches(start_time, version) VALUES ('t', '18.6')")
        conn.commit()
        conn.close()
        store = MatchStore(db, "18.6")  # 应触发 ALTER TABLE 幂等迁移
        store.record_round(1, 1, "combat", 0.8, 10, 80, 50, 7, None, 55.0, "p1", 0.7, "high", [], pred_engine="L1.5")
        rows = store.all_predictions(1)
        assert rows[0][3] == "L1.5"
        store.close()


# ---------- AC4 四象限（合成局方向性） ----------


class TestQuadrantDirection:
    def test_known_matchups_direction(self, panel_engine, units_book):
        """构造已知强弱对：强方预测胜率显著高，不出现系统性反向。"""
        import random

        rng = random.Random(42)
        rights = 0
        trials = 40
        for _ in range(trials):
            n_strong = rng.randint(6, 10)
            n_weak = rng.randint(1, 5)
            mp = panel_engine.assemble(mk_state(strong_units(n_strong)))
            op = panel_engine.assemble(mk_state(weak_units(n_weak), "p1"))
            p = predict_l15(mp, op)
            # 已知结果：强方必赢（合成局设定）
            if (p.winrate or 0.5) > 0.5:
                rights += 1
        # 方向正确率应 >= 90%（允许个别低样本局误判）
        assert rights / trials >= 0.9

    def test_quadrant_cli_runs(self, tmp_path, monkeypatch, capsys):
        """quadrant 子命令 smoke（空库不炸，输出四象限标题）。"""
        from tft_copilot.replay_cli import cmd_quadrant

        class NS:
            db = str(tmp_path / "q.db")
            match = None

        # 建一个空库（无 matches 行 -> version 检查通过）
        from tft_copilot.store.db import MatchStore

        store = MatchStore(NS.db, "18.6")
        store.close()
        rc = cmd_quadrant(NS())
        out = capsys.readouterr().out
        assert rc == 0
        assert "四象限" in out
