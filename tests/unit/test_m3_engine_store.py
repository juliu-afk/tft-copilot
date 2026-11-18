"""M3 存储层/引擎/HUD/CLI 测试（技术方案 §11）。"""

from __future__ import annotations

import csv

import pytest

from tft_copilot.decision.engine import DecisionEngine
from tft_copilot.decision.snapshot import BoardSnapshot, PlayerState, UnitOnBoard
from tft_copilot.knowledge.rules_loader import load_rules
from tft_copilot.knowledge.units_loader import UnitsBook
from tft_copilot.overlay.hud import ConsoleHUD, HUDState, create_hud
from tft_copilot.store.db import MatchStore, MatchStoreVersionError


@pytest.fixture(scope="module")
def book():
    return UnitsBook.from_file("data/units/units_18.6.json")


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture
def store(tmp_path):
    s = MatchStore(tmp_path / "test.db", "18.6")
    yield s
    s.close()


# ---------- 存储层 ----------

class TestMatchStore:
    def test_start_and_round(self, store):
        mid = store.start_match()
        assert mid >= 1
        store.record_round(mid, 1, "shop", 0.9, 100, 80, 50, 8, None, 25.0, "p2", 0.62, "mid", None)
        rounds = store.get_rounds(mid)
        assert len(rounds) == 1
        assert rounds[0]["layers"] == 100
        assert store.db_version == "18.6"

    def test_close_match(self, store):
        mid = store.start_match()
        store.close_match(mid, 2, 620, "WWLL")
        m = store.get_match(mid)
        assert m["final_place"] == 2 and m["win_loss"] == "WWLL"
        assert m["end_time"] is not None

    def test_unclosed_detection(self, store):
        a = store.start_match()
        b = store.start_match()
        store.close_match(a, 1, 100, "W")
        assert store.open_unclosed() == [b]  # US-6b 断线续采

    def test_version_mismatch_rejected(self, store, tmp_path):
        store.start_match()  # 锚定 18.6
        store.close_match(store.open_unclosed()[0], 1, 1, "W")
        p = tmp_path / "test.db"
        with pytest.raises(MatchStoreVersionError):
            MatchStore(p, "18.7")  # 铁律：版本不匹配拒写

    def test_record_result_validation(self, store):
        mid = store.start_match()
        store.record_round(mid, 1, None, None, None, None, None, None, None, None, None, None, None, None)
        with pytest.raises(ValueError):
            store.record_result(mid, 1, "X")
        store.record_result(mid, 1, "W")
        r = store.get_rounds(mid)
        assert r[0]["actual_result"] == "W"

    def test_win_loss_validation(self, store):
        mid = store.start_match()
        with pytest.raises(ValueError):
            store.close_match(mid, 1, 1, "WX")

    def test_all_predictions(self, store):
        mid = store.start_match()
        store.record_round(mid, 1, None, None, 1, None, None, None, None, None, "p1", 0.7, "high", None)
        store.record_round(mid, 2, None, None, 2, None, None, None, None, None, "p2", None, None, None)
        store.record_result(mid, 1, "W")
        preds = store.all_predictions()
        assert len(preds) == 1  # 只含 winrate 非 None 的行


# ---------- 引擎 ----------

def _snap(round_no, layers, hp, quality=0.95, units=None):
    return BoardSnapshot(
        round_no=round_no, scene="shop", quality=quality,
        my_units=units or [], layers=layers, hp=hp, gold=50, level=8,
    )


class TestDecisionEngine:
    def test_full_round_chain(self, rules, book, store):
        eng = DecisionEngine(rules, book, store=store, hud=ConsoleHUD(quiet=True))
        mid = eng.start_match()
        ids = [u.id for u in book][:8]
        players = {
            "me": PlayerState("me", [UnitOnBoard(i, 1, 2, 0.99) for i in ids], 80, [80]),
            "p1": PlayerState("p1", [UnitOnBoard(i, 1, 1, 0.99) for i in ids[:6]], 70, [70]),
        }
        advices = eng.on_round(_snap(1, 100, 80, units=players["me"].units), players, next_opp="p1")
        assert isinstance(advices, list)
        assert store.get_rounds(mid)  # 已落库

    def test_silent_when_low_quality(self, rules, book):
        eng = DecisionEngine(rules, book, hud=ConsoleHUD(quiet=True))
        eng.start_match()
        advices = eng.on_round(_snap(1, 100, 80, quality=0.2))
        assert advices == []  # E1

    def test_layer_guard_in_engine(self, rules, book, store):
        """引擎内层数卫兵：跳变帧读数被丢弃（不更新层数相关建议）。"""
        eng = DecisionEngine(rules, book, store=store, hud=ConsoleHUD(quiet=True))
        eng.start_match()
        eng.on_round(_snap(1, 100, 80))
        advs = eng.on_round(_snap(2, 400, 80))  # 跳变 300 -> 卫兵丢弃，无里程碑误触发
        assert not any("400" in a.text for a in advs)

    def test_budget_50ms(self, rules, book):
        """A8：单轮全链路 <=50ms。"""
        import time
        eng = DecisionEngine(rules, book, hud=ConsoleHUD(quiet=True))
        eng.start_match()
        ids = [u.id for u in book]
        players = {
            name: PlayerState(name, [UnitOnBoard(ids[i % 122], 1, 2, 0.99) for i in range(10)], 80, [80])
            for name in ["me"] + [f"p{j}" for j in range(1, 8)]
        }
        worst = 0.0
        for r in range(1, 21):
            snap = _snap(r, r * 10, 80, units=players["me"].units)
            t0 = time.perf_counter()
            eng.on_round(snap, players, next_opp="p3")
            worst = max(worst, time.perf_counter() - t0)
        assert worst * 1000 < 50

    def test_dedup_advice(self, rules, book):
        """同源同前缀文案去重。"""
        from tft_copilot.decision.snapshot import Advice
        advs = [
            Advice("info", "下一档奖励：4金币，还差 1 层", "layer_progress"),
            Advice("info", "下一档奖励：4金币，还差 1 层", "layer_progress"),
            Advice("info", "另一条不同文案", "impact"),
        ]
        assert len(DecisionEngine._dedup(advs)) == 2

    def test_record_and_close(self, rules, book, store):
        eng = DecisionEngine(rules, book, store=store, hud=ConsoleHUD(quiet=True))
        mid = eng.start_match()
        eng.on_round(_snap(1, 10, 80))
        eng.record_result(1, "W")
        eng.close_match(1, 400, "W")
        m = store.get_match(mid)
        assert m["win_loss"] == "W" and m["end_time"]


# ---------- HUD ----------

class TestHUD:
    def test_console_update(self, capsys):
        h = ConsoleHUD()
        h.update(HUDState(layers=300, next_milestone=400, dist_to_milestone=100,
                          players=[("me", 45.0), ("p1", None)], round_no=5, match_id=1))
        out = capsys.readouterr().out
        assert "层数 300" in out and "p1:?" in out

    def test_console_toast_colors(self, capsys):
        h = ConsoleHUD()
        h.toast("critical", "红色测试")
        assert "红色测试" in capsys.readouterr().out

    def test_factory_fallback(self):
        """A7：无 PyQt6 环境工厂回落 ConsoleHUD。"""
        h = create_hud("auto")
        assert isinstance(h, ConsoleHUD)

    def test_factory_console(self):
        assert isinstance(create_hud("console"), ConsoleHUD)


# ---------- CLI ----------

class TestCLI:
    def test_decision_test_smoke(self, tmp_path):
        from tft_copilot.decision_check import run as dt_run

        class Args:
            db = str(tmp_path / "smoke.db")
            rounds = 8
            seed = 42

        rc = dt_run(Args)
        assert rc == 0
        assert (tmp_path / "smoke.db").exists()

    def test_replay_cmd(self, tmp_path, capsys):
        # 先造一局
        from tft_copilot.decision_check import run as dt_run

        class DtArgs:
            db = str(tmp_path / "r.db")
            rounds = 5
            seed = 7

        dt_run(DtArgs)

        from tft_copilot.replay_cli import cmd_replay

        class RpArgs:
            db = str(tmp_path / "r.db")
            match = 1
            round = None

        rc = cmd_replay(RpArgs)
        out = capsys.readouterr().out
        assert rc == 0 and "对局 1" in out

    def test_stats_cmd(self, tmp_path, capsys):
        from tft_copilot.decision_check import run as dt_run
        from tft_copilot.replay_cli import cmd_stats

        class DtArgs:
            db = str(tmp_path / "s.db")
            rounds = 5
            seed = 7

        dt_run(DtArgs)

        class StArgs:
            db = str(tmp_path / "s.db")
            match = None

        rc = cmd_stats(StArgs)
        out = capsys.readouterr().out
        assert rc == 0 and "四象限" in out and "样本不足" in out

    def test_export_cmd(self, tmp_path):
        from tft_copilot.decision_check import run as dt_run
        from tft_copilot.replay_cli import cmd_export

        class DtArgs:
            db = str(tmp_path / "e.db")
            rounds = 5
            seed = 7

        dt_run(DtArgs)

        class ExArgs:
            db = str(tmp_path / "e.db")
            csv = str(tmp_path / "out")

        assert cmd_export(ExArgs) == 0
        with open(tmp_path / "out" / "matches.csv", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 1
        with open(tmp_path / "out" / "rounds.csv", encoding="utf-8-sig") as f:
            assert len(list(csv.DictReader(f))) == 5
