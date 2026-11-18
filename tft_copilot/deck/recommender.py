"""组合推演器（M4）：剪枝 + Top5 + 阶段策略说明。

剪枝三重：单卡预打分 Top60% 入池 / 星线均值约束 / 同 tag 多样性惩罚。
全流程预算 ≤5s（PRD A4）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from itertools import combinations

from tft_copilot.deck.combo_scorer import (
    ComboScorer,
    DeckCombo,
    resolve_task_tags,
    score_combo,
)
from tft_copilot.knowledge.cards_loader import CardsBook, TimeCard

# 剪枝参数（PRD Q3-A）
POOL_RATIO = 0.6  # 单卡预打分 Top60% 入池
STAR_MEAN_CAP = 3.5  # 三卡平均星上限（运营可行性）
DUP_TAG_PENALTY = 0.06  # 组合内同 tag 重复惩罚（每多一张同 tag）
TOP_K = 5

# 偏好档位
PREFERENCES = ("balanced", "economy", "aggressive", "gate")


@dataclass(frozen=True)
class RecommendResult:
    """推荐输出：Top5 组合 + 元信息。"""

    combos: tuple[DeckCombo, ...]
    pool_size: int
    candidates: int
    elapsed_s: float
    preference: str


# 偏好 -> 任务 tags 修正
_PREF_TASK_TAGS = {
    "balanced": None,
    "economy": ["economy", "xp"],
    "aggressive": ["combat", "sustain"],
    "gate": ["trait-bridge"],
}

# 阶段策略说明：tag -> 段文案（模板化，非自由文本）
_PHASE_TEXT = {
    "economy": "前期攒钱：经济卡保证利息与升级节奏，稳定血量过度",
    "xp": "前期提速：经验卡加快等级，抢占高费卡刷新窗口",
    "combat": "中期发力：战斗增益卡提升战力，赢下关键回合",
    "sustain": "中期保血：续航卡降低掉血速度，为后期成型留容错",
    "trait-bridge": "后期成型：桥梁卡通往核心羁绊，成型后战力质变",
    "reroll": "中期追三：刷牌卡支撑低费追三星节奏",
    "item": "中期装备：装备卡补足核心 C 位神装",
    "copy": "后期复制：复制卡翻倍关键单位，二次成型",
    "generic": "过渡平滑：综合效应稳住各阶段强度曲线",
}

_PHASE_ORDER = ("前期", "中期", "后期")


def _phase_sort_key(tag: str) -> int:
    order = {"economy": 0, "xp": 0, "generic": 0, "combat": 1, "sustain": 1, "reroll": 1, "item": 1,
             "trait-bridge": 2, "copy": 2}
    return order.get(tag, 1)


def build_phase_notes(combo: DeckCombo) -> list[str]:
    """三段式阶段策略说明（前期/中期/后期各一句）。"""
    tags = []
    for c in combo.cards:
        for t in c.effect_tags:
            if t not in tags:
                tags.append(t)
    tags.sort(key=_phase_sort_key)
    notes: list[str] = []
    used = 0
    for t in tags:
        if used >= 3:
            break
        notes.append(_PHASE_TEXT.get(t, _PHASE_TEXT["generic"]))
        used += 1
    while len(notes) < 3:
        notes.append(_PHASE_TEXT["generic"])
    return notes[:3]


def _dup_tag_penalty(cards: tuple[TimeCard, ...]) -> float:
    """同 tag 重复惩罚：任一 tag 在组合内出现 ≥2 次，每多一张扣分。"""
    from collections import Counter

    cnt: Counter[str] = Counter()
    for c in cards:
        cnt.update(c.effect_tags)
    return sum(n - 1 for n in cnt.values() if n > 1) * DUP_TAG_PENALTY


class DeckRecommender:
    """组合推演器。"""

    def __init__(self, book: CardsBook) -> None:
        self._book = book
        self._scorer = ComboScorer(book)

    def recommend(
        self,
        preference: str = "balanced",
        task_name: str | None = None,
        pool_ratio: float = POOL_RATIO,
        top_k: int = TOP_K,
    ) -> RecommendResult:
        """全流程：预打分 -> 剪枝池 -> C(n,3) 枚举 -> TopK。"""
        t0 = time.perf_counter()
        if preference not in PREFERENCES:
            raise ValueError(f"未知偏好: {preference!r}，可选 {PREFERENCES}")
        base_tags = resolve_task_tags(task_name)
        pref_tags = _PREF_TASK_TAGS[preference]
        task_tags = pref_tags if pref_tags else base_tags

        # 剪枝1：单卡预打分排序取 Top60%
        single = self._scorer.single_scores(task_tags)
        ranked = sorted(self._book, key=lambda c: -single[c.id])
        pool = ranked[: max(3, int(len(ranked) * pool_ratio))]
        pool_ids = [c.id for c in pool]

        # 剪枝2+3：星线均值 + 同 tag 惩罚在枚举内联
        best: list[tuple[float, DeckCombo]] = []
        n_cand = 0
        for a, b, d in combinations(pool_ids, 3):
            cards = (self._book.by_id(a), self._book.by_id(b), self._book.by_id(d))
            mean_star = sum(c.star for c in cards) / 3
            if mean_star > STAR_MEAN_CAP:
                continue
            n_cand += 1
            combo = score_combo(cards, task_tags)
            total = combo.total - _dup_tag_penalty(cards)
            best.append((total, combo))
        best.sort(key=lambda kv: -kv[0])
        top = tuple(c for _, c in best[:top_k])
        elapsed = time.perf_counter() - t0
        return RecommendResult(
            combos=top,
            pool_size=len(pool),
            candidates=n_cand,
            elapsed_s=elapsed,
            preference=preference,
        )

    def describe(self, result: RecommendResult) -> str:
        """推荐结果 -> 人读文本（Top5 + 三段说明）。"""
        lines = [
            f"偏好 {result.preference} | 候选池 {result.pool_size} 卡 | "
            f"有效组合 {result.candidates} | 耗时 {result.elapsed_s:.2f}s"
        ]
        for i, combo in enumerate(result.combos, 1):
            names = " + ".join(f"{c.name}({c.star}星)" for c in combo.cards)
            lines.append("")
            lines.append(f"Top{i}  总分 {combo.total:.3f}  [{combo.tag_summary}]")
            lines.append(f"  组合: {names}")
            notes = build_phase_notes(combo)
            for phase, note in zip(_PHASE_ORDER, notes, strict=True):
                lines.append(f"  {phase}: {note}")
            if combo.desc_missing_count:
                lines.append(f"  （{combo.desc_missing_count}/3 卡效果描述待人工校验）")
        return chr(10).join(lines)
