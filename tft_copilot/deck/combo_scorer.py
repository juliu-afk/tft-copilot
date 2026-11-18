"""四维评分引擎（M4）：强度曲线 / 任务兼容 / 传送门匹配 / 成型难度。

权重来自设计文档 7.3 节（PRD Q2 选 A）。全部计算基于 effect_tags 骨架，
desc_missing 卡透明降级参与评分。
"""

from __future__ import annotations

from dataclasses import dataclass

from tft_copilot.knowledge.cards_loader import CardsBook, TimeCard

# 设计文档 7.3 权重
W_STRENGTH = 0.35
W_TASK = 0.30
W_GATE = 0.20
W_DIFFICULTY = 0.15

# tag 基础强度分（1-5 星卡的典型效应强度，M6 校准）
TAG_STRENGTH = {
    "economy": 3.0,
    "xp": 3.0,
    "trait-bridge": 4.0,
    "combat": 3.5,
    "sustain": 2.5,
    "reroll": 2.5,
    "item": 3.0,
    "copy": 3.5,
    "generic": 1.5,
}

# 星级对强度的乘数（5 星卡效应通常强于同名低星）
STAR_MULT = {1: 0.8, 2: 0.9, 3: 1.0, 4: 1.1, 5: 1.2}

# 星级对运营难度的负担（高星更难成型）
STAR_BURDEN = {1: 0.2, 2: 0.35, 3: 0.5, 4: 0.7, 5: 0.9}

# 任务关键词 -> 兼容 tags（rules 库 38 任务的典型需求映射）
TASK_TAG_AFFINITY = {
    "连胜": ["combat", "sustain", "economy"],
    "连败": ["economy", "xp"],
    "层数": ["economy", "xp"],
    "弈子": ["trait-bridge", "reroll", "copy"],
    "星级": ["reroll", "economy"],
    "羁绊": ["trait-bridge"],
    "装备": ["item"],
    "经济": ["economy"],
    "通用": ["economy", "xp", "trait-bridge"],
}


@dataclass(frozen=True)
class DeckCombo:
    """三卡组合评分结果。"""

    cards: tuple[TimeCard, ...]
    strength: float
    task_compat: float
    gate_match: float
    difficulty: float
    total: float

    @property
    def tag_summary(self) -> str:
        tags: list[str] = []
        for c in self.cards:
            for t in c.effect_tags:
                if t not in tags:
                    tags.append(t)
        return "/".join(tags)

    @property
    def desc_missing_count(self) -> int:
        return sum(1 for c in self.cards if "desc_missing" in c.quality_flags)


def card_strength(c: TimeCard) -> float:
    """单卡强度分：tag 均值 × 星级乘数。"""
    base = sum(TAG_STRENGTH.get(t, 1.5) for t in c.effect_tags) / len(c.effect_tags)
    return base * STAR_MULT.get(c.star, 1.0)


def card_task_compat(c: TimeCard, task_tags: list[str]) -> float:
    """单卡任务兼容：tags 交集 / 任务需求 tags 数。"""
    if not task_tags:
        task_tags = TASK_TAG_AFFINITY["通用"]
    hit = sum(1 for t in task_tags if t in c.effect_tags)
    return min(hit / len(task_tags), 1.0)


def combo_strength(cards: tuple[TimeCard, ...]) -> float:
    """强度曲线（0-1）：三卡强度均值归一（基准 5 分满）。"""
    s = sum(card_strength(c) for c in cards) / len(cards)
    return min(s / 5.0, 1.0)


def combo_task_compat(cards: tuple[TimeCard, ...], task_tags: list[str]) -> float:
    """任务兼容（0-1）：三卡兼容均值。"""
    return sum(card_task_compat(c, task_tags) for c in cards) / len(cards)


def combo_gate_match(cards: tuple[TimeCard, ...]) -> float:
    """传送门匹配（0-1）：trait-bridge 卡存在即得基础分，多卡递增。"""
    n_bridge = sum(1 for c in cards if "trait-bridge" in c.effect_tags)
    if n_bridge == 0:
        # 无桥梁卡但有 combat/sustain 组合也具备过渡能力（0.2 基线）
        has_alt = any(t in ("combat", "sustain") for c in cards for t in c.effect_tags)
        return 0.2 if has_alt else 0.0
    return min(0.5 + 0.25 * (n_bridge - 1), 1.0)


def combo_difficulty(cards: tuple[TimeCard, ...]) -> float:
    """成型难度（0-1，越高越难）：三卡星级负担均值。"""
    return sum(STAR_BURDEN.get(c.star, 0.5) for c in cards) / len(cards)


def score_combo(cards: tuple[TimeCard, ...], task_tags: list[str] | None = None) -> DeckCombo:
    """四维加权总分（0-1）。难度是负向维度：难度越高得分越低。"""
    tags = task_tags or []
    strength = combo_strength(cards)
    task = combo_task_compat(cards, tags)
    gate = combo_gate_match(cards)
    diff = combo_difficulty(cards)
    total = W_STRENGTH * strength + W_TASK * task + W_GATE * gate + W_DIFFICULTY * (1.0 - diff)
    return DeckCombo(
        cards=cards,
        strength=strength,
        task_compat=task,
        gate_match=gate,
        difficulty=diff,
        total=total,
    )


def resolve_task_tags(task_name: str | None) -> list[str]:
    """任务名 -> 兼容 tags（关键词匹配，M6 校准）。"""
    if not task_name:
        return list(TASK_TAG_AFFINITY["通用"])
    for kw, tags in TASK_TAG_AFFINITY.items():
        if kw in task_name:
            return list(tags)
    return list(TASK_TAG_AFFINITY["通用"])


class ComboScorer:
    """批量评分入口：预打分 + 组合打分。"""

    def __init__(self, book: CardsBook) -> None:
        self._book = book
        self._cards = {c.id: c for c in book}

    def single_scores(self, task_tags: list[str] | None = None) -> dict[int, float]:
        """单卡预打分（剪枝依据）：四维中可单卡计算的三个 + 难度。"""
        tags = task_tags or []
        out: dict[int, float] = {}
        for c in self._book:
            s = card_strength(c) / 5.0
            t = card_task_compat(c, tags)
            g = 1.0 if "trait-bridge" in c.effect_tags else 0.2
            d = 1.0 - STAR_BURDEN.get(c.star, 0.5)
            out[c.id] = W_STRENGTH * s + W_TASK * t + W_GATE * g + W_DIFFICULTY * d
        return out

    def score(self, card_ids: tuple[int, ...], task_tags: list[str] | None = None) -> DeckCombo:
        cards = tuple(self._cards[i] for i in card_ids)
        return score_combo(cards, task_tags)
