"""M4 卡组参谋测试：loader 三重校验 + 评分引擎 + 推演器 + M3 联动。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tft_copilot.deck.combo_scorer import (
    card_strength,
    combo_difficulty,
    combo_gate_match,
    combo_strength,
    resolve_task_tags,
    score_combo,
)
from tft_copilot.deck.recommender import (
    DUP_TAG_PENALTY,
    PREFERENCES,
    DeckRecommender,
    build_phase_notes,
)
from tft_copilot.knowledge.cards_loader import (
    CardsDataError,
    TimeCard,
    desc_review_list,
    load_cards,
)
from tft_copilot.knowledge.traits_loader import (
    TraitsDataError,
    load_traits,
)

DATA = Path(__file__).resolve().parents[2] / "data"


# ---------- 卡片库 loader ----------


class TestCardsLoader:
    def test_load_201(self):
        book = load_cards()
        assert len(book) == 201
        assert book.star_dist == {1: 20, 2: 30, 3: 60, 4: 50, 5: 41}

    def test_no_dup_names(self):
        book = load_cards()
        names = [c.name for c in book]
        assert len(set(names)) == 201

    def test_version_mismatch_rejected(self, tmp_path):
        src = DATA / "cards" / "cards_18.6.json"
        bad = tmp_path / "cards_18.7.json"
        bad.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        with pytest.raises(CardsDataError, match="18.6"):
            load_cards(bad, patch="18.7")

    def test_meta_patch_mismatch_rejected(self, tmp_path):
        """文件名 18.6 但 meta.patch=18.9：文件名检查放行后 meta 校验须拦截。"""
        raw = json.loads((DATA / "cards" / "cards_18.6.json").read_text(encoding="utf-8"))
        raw["meta"]["patch"] = "18.9"
        p = tmp_path / "cards_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(CardsDataError, match="meta.patch"):
            load_cards(p, patch="18.6")

    def test_star_dist_mismatch_rejected(self, tmp_path):
        raw = json.loads((DATA / "cards" / "cards_18.6.json").read_text(encoding="utf-8"))
        raw["meta"]["star_dist"]["1"] = 99
        p = tmp_path / "cards_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(CardsDataError):
            load_cards(p)

    def test_bad_star_rejected(self, tmp_path):
        raw = json.loads((DATA / "cards" / "cards_18.6.json").read_text(encoding="utf-8"))
        raw["cards"][0]["star"] = "三"
        p = tmp_path / "cards_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(CardsDataError, match="star"):
            load_cards(p)

    def test_unknown_tag_rejected(self, tmp_path):
        raw = json.loads((DATA / "cards" / "cards_18.6.json").read_text(encoding="utf-8"))
        raw["cards"][0]["effect_tags"] = ["hack"]
        p = tmp_path / "cards_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(CardsDataError, match="effect_tags"):
            load_cards(p)

    def test_by_star_by_tag(self):
        book = load_cards()
        assert len(book.by_star(5)) == 41
        assert len(book.by_tag("trait-bridge")) > 0
        with pytest.raises(CardsDataError):
            book.by_id(999999)

    def test_desc_review_list(self):
        book = load_cards()
        lst = desc_review_list(book)
        assert len(lst) == 201  # 当前全部待校验
        assert {"id", "name", "star", "effect_tags"} <= set(lst[0])


# ---------- 羁绊 loader ----------


class TestTraitsLoader:
    def test_load_58(self):
        book = load_traits()
        assert len(book) == 58
        assert all(t.num_list for t in book)

    def test_breakpoint_weight(self):
        book = load_traits()
        t = book.by_name("斗士")
        assert t.num_list == (2, 4, 6)
        assert t.breakpoint_weight(0) == 0.0
        assert t.breakpoint_weight(2) == pytest.approx(1 / 3)
        assert t.breakpoint_weight(6) == 1.0
        assert t.max_breakpoint == 6

    def test_member_map(self):
        book = load_traits()
        mmap = book.member_trait_map()
        assert "斗士" in mmap[11402]

    def test_version_rejected(self, tmp_path):
        src = DATA / "traits" / "traits_18.6.json"
        bad = tmp_path / "traits_18.7.json"
        bad.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        with pytest.raises(TraitsDataError):
            load_traits(bad, patch="18.7")

    def test_empty_members_rejected(self, tmp_path):
        raw = json.loads((DATA / "traits" / "traits_18.6.json").read_text(encoding="utf-8"))
        raw["traits"][0]["members"] = []
        p = tmp_path / "traits_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(TraitsDataError, match="members"):
            load_traits(p)

    def test_num_list_order_rejected(self, tmp_path):
        raw = json.loads((DATA / "traits" / "traits_18.6.json").read_text(encoding="utf-8"))
        raw["traits"][0]["num_list"] = [6, 4, 2]
        p = tmp_path / "traits_18.6.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(TraitsDataError, match="num_list"):
            load_traits(p)


# ---------- 评分引擎 ----------


def _card(name: str, star: int, tags: tuple[str, ...]) -> TimeCard:
    return TimeCard(
        id=hash(name) % 10_000_000,
        name=name,
        star=star,
        icon="",
        effect_desc=None,
        effect_tags=tags,
        energy_cost=None,
        quality_flags=("desc_missing",),
    )


class TestScorer:
    def test_card_strength_monotonic_in_star(self):
        lo = _card("测试 I", 1, ("economy",))
        hi = _card("测试 V", 5, ("economy",))
        assert card_strength(hi) > card_strength(lo)

    def test_tag_strength_ordering(self):
        bridge = _card("桥梁", 3, ("trait-bridge",))
        generic = _card("杂卡", 3, ("generic",))
        assert card_strength(bridge) > card_strength(generic)

    def test_combo_strength_range(self):
        cs = (_card("a", 3, ("economy",)), _card("b", 3, ("combat",)), _card("c", 3, ("item",)))
        s = combo_strength(cs)
        assert 0.0 < s <= 1.0

    def test_gate_match_with_bridge(self):
        with_bridge = (_card("a", 3, ("trait-bridge",)), _card("b", 3, ("economy",)), _card("c", 3, ("xp",)))
        no_bridge = (_card("a", 3, ("economy",)), _card("b", 3, ("xp",)), _card("c", 3, ("item",)))
        assert combo_gate_match(with_bridge) > combo_gate_match(no_bridge)

    def test_difficulty_higher_with_stars(self):
        lo = (_card("a", 1, ("economy",)), _card("b", 1, ("xp",)), _card("c", 1, ("item",)))
        hi = (_card("a", 5, ("economy",)), _card("b", 5, ("xp",)), _card("c", 5, ("item",)))
        assert combo_difficulty(hi) > combo_difficulty(lo)

    def test_task_compat_resolution(self):
        assert "combat" in resolve_task_tags("连胜")
        assert "economy" in resolve_task_tags(None)

    def test_score_combo_weights_sum(self):
        cs = (_card("a", 3, ("economy",)), _card("b", 3, ("combat",)), _card("c", 3, ("item",)))
        combo = score_combo(cs, ["economy"])
        assert 0.0 <= combo.total <= 1.0
        assert combo.desc_missing_count == 3


# ---------- 推演器 ----------


class TestRecommender:
    def test_all_preferences_under_5s(self):
        book = load_cards()
        r = DeckRecommender(book)
        for pref in PREFERENCES:
            res = r.recommend(pref)
            assert res.elapsed_s < 5.0, f"{pref} 超时 {res.elapsed_s:.2f}s"
            assert len(res.combos) == 5

    def test_star_mean_cap(self):
        book = load_cards()
        r = DeckRecommender(book)
        res = r.recommend("balanced")
        for combo in res.combos:
            mean = sum(c.star for c in combo.cards) / 3
            assert mean <= 3.5 + 1e-9

    def test_top5_sorted(self):
        book = load_cards()
        r = DeckRecommender(book)
        res = r.recommend("balanced")
        totals = [c.total for c in res.combos]
        assert totals == sorted(totals, reverse=True)

    def test_phase_notes_three_segments(self):
        cs = (
            _card("经济", 1, ("economy",)),
            _card("战斗", 3, ("combat",)),
            _card("桥梁", 4, ("trait-bridge",)),
        )
        combo = score_combo(cs, None)
        notes = build_phase_notes(combo)
        assert len(notes) == 3
        assert all(isinstance(n, str) and n for n in notes)

    def test_invalid_preference_rejected(self):
        book = load_cards()
        r = DeckRecommender(book)
        with pytest.raises(ValueError, match="偏好"):
            r.recommend("hack")

    def test_perf_full_run(self):
        book = load_cards()
        r = DeckRecommender(book)
        t0 = time.perf_counter()
        res = r.recommend("balanced")
        wall = time.perf_counter() - t0
        assert wall < 5.0
        assert res.candidates > 100_000  # 剪枝后仍有 10 万级组合

    def test_dup_tag_penalty_value(self):
        cs = (
            _card("经济A", 1, ("economy",)),
            _card("经济B", 1, ("economy",)),
            _card("战斗", 3, ("combat",)),
        )
        from tft_copilot.deck.recommender import _dup_tag_penalty

        assert _dup_tag_penalty(cs) == pytest.approx(DUP_TAG_PENALTY)


# ---------- M3 联动 ----------


class TestEngineDeckPlan:
    def test_deck_plan_advice_once(self):
        from tft_copilot.decision.engine import DecisionEngine
        from tft_copilot.decision.snapshot import BoardSnapshot
        from tft_copilot.knowledge.rules_loader import load_rules
        from tft_copilot.knowledge.units_loader import UnitsBook
        from tft_copilot.overlay.hud import ConsoleHUD

        rules = load_rules()
        book = UnitsBook.from_file(DATA / "units" / "units_18.6.json")
        eng = DecisionEngine(
            rules, book, hud=ConsoleHUD(quiet=True),
            deck_plan=("纹章之书 I", "白银之选", "小额奖金 I"),
        )
        eng.start_match()
        advs1 = eng.on_round(BoardSnapshot(1, "shop", 0.95, [], 100, 80, 50, 8))
        assert any(a.source == "deck_plan" for a in advs1)
        advs2 = eng.on_round(BoardSnapshot(2, "shop", 0.95, [], 105, 80, 50, 8))
        assert not any(a.source == "deck_plan" for a in advs2)

    def test_no_deck_plan_no_advice(self):
        from tft_copilot.decision.engine import DecisionEngine
        from tft_copilot.decision.snapshot import BoardSnapshot
        from tft_copilot.knowledge.rules_loader import load_rules
        from tft_copilot.knowledge.units_loader import UnitsBook
        from tft_copilot.overlay.hud import ConsoleHUD

        rules = load_rules()
        book = UnitsBook.from_file(DATA / "units" / "units_18.6.json")
        eng = DecisionEngine(rules, book, hud=ConsoleHUD(quiet=True))
        eng.start_match()
        advs = eng.on_round(BoardSnapshot(1, "shop", 0.95, [], 100, 80, 50, 8))
        assert not any(a.source == "deck_plan" for a in advs)
