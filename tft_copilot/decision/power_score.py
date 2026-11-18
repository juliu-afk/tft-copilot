"""模块(2) 战力评分：四分量加权（工程方案 5.2）。

budget: 决策侧 <5ms/次（122 弈子数值查表）。
红线自查：零网络、零输入模拟、零进程读取。

分量说明（D5 初始权重，M6 回归重估）：
- star 星级分：按 stars 表逐行数值 (hp + 10*ad)/1000，无固定映射表（D3）
- trait 羁绊分：激活数近似 sum(min(count,6))*1.5，M4 换断点表（D1）
- item 成装分：本迭代恒 0，装备识别 M5
- trend 血量趋势分：近5回合血量平均斜率
"""

from __future__ import annotations

from collections import Counter

from tft_copilot.decision.snapshot import PlayerState, UnitOnBoard
from tft_copilot.knowledge.units_loader import KnowledgeError, UnitsBook

# 四分量权重（工程方案 5.2 初始值，M6 每50局回归重估）
W_STAR, W_TRAIT, W_ITEM, W_TREND = 0.35, 0.25, 0.25, 0.15
# 羁绊单激活数权重与上限（D1 近似：无断点表，用激活数）
TRAIT_UNIT_WEIGHT = 1.5
TRAIT_CAP = 100.0
# 星级行能量基准：unit_power = (hp + 10*ad)/1000
UNIT_POWER_DIV = 1000.0
UNIT_POWER_AD_MULT = 10.0
# 满配基准：10 个弈子，每格能量取全库 star3 行最大值（加载期算，无魔法常数）
BOARD_SIZE = 10
# 血量趋势：50 为稳态中线，斜率系数
TREND_BASE = 50.0
TREND_SLOPE_MULT = 5.0
# 低于此费用的单子视为炮灰不影响星级分（防一费卡刷分）——不对，一费卡也占格，
# 星级分本身就是质量度量，无需费用过滤。保留全部弈子。


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


class PowerScorer:
    """给一家 PlayerState 打 0-100 战力分。"""

    def __init__(self, book: UnitsBook) -> None:
        self._book = book
        # 满配基准：全库 star==3 行平均能量 x 10 格（版本典型成型线）。
        # WHY: 一星均 1.42 / 二星 2.36 / 三星均 5.21 / 六星顶 27.6——
        # 以三星均值 x10 为 100 分锚点，一星阵容约 27 分、六星顶配 clamp 100，
        # 梯度区分度最好；star>=3 混档会把基准拉高到无人能达，失去区分度。
        rows = [r for u in book for r in u.stars if r.star == 3]
        avg = (
            sum((r.hp + UNIT_POWER_AD_MULT * r.ad) / UNIT_POWER_DIV for r in rows) / len(rows)
            if rows
            else 1.0
        )
        self._board_max = BOARD_SIZE * max(avg, 1e-6)

    def score(self, state: PlayerState) -> float | None:
        """返回 0-100 分；units 未侦查(None)返回 None（诚实原则）。"""
        if state.units is None:
            return None
        units = [u for u in state.units if u.score >= 0.45]  # pending 剔除（A2）
        star = self.star_score(units)
        trait = self.trait_score(units)
        item = 0.0
        trend = self.trend_score(state.hp_history)
        total = W_STAR * star + W_TRAIT * trait + W_ITEM * item + W_TREND * trend
        return round(_clamp(total), 1)

    def star_score(self, units: list[UnitOnBoard]) -> float:
        """星级分：Σ弈子能量 / 满配基准 * 100。star=None 按一星（E4）。"""
        total = 0.0
        for u in units:
            try:
                unit = self._book.get_unit(u.unit_id)
            except KnowledgeError:
                continue  # 未知棋子（数据缺）不计分，诚实跳过
            star = u.star if u.star is not None else 1
            row = self._pick_row(unit.stars, star)
            total += (row.hp + UNIT_POWER_AD_MULT * row.ad) / UNIT_POWER_DIV
        return _clamp(total / self._board_max * 100.0)

    def trait_score(self, units: list[UnitOnBoard]) -> float:
        """羁绊分：激活数近似（D1）。上限 clamp 100。"""
        counts: Counter[str] = Counter()
        for u in units:
            try:
                unit = self._book.get_unit(u.unit_id)
            except KnowledgeError:
                continue
            for t in unit.traits:
                counts[t] += 1
        raw = sum(min(c, 6) for c in counts.values()) * TRAIT_UNIT_WEIGHT
        return _clamp(raw)

    @staticmethod
    def trend_score(hp_history: list[int]) -> float:
        """血量趋势分：近5回合平均每回合变化斜率（掉血快分低）。"""
        if len(hp_history) < 2:
            return TREND_BASE  # 数据不足按中线
        slopes = [
            hp_history[i + 1] - hp_history[i] for i in range(len(hp_history) - 1)
        ]
        mean_slope = sum(slopes) / len(slopes)
        # slope>0 回血（高位保血期）加分；slope<0 掉血（阵容未成型）减分
        return _clamp(TREND_BASE + mean_slope * TREND_SLOPE_MULT)

    @staticmethod
    def _pick_row(stars: tuple, star: int) -> object:
        """按目标星级选行；stars 覆盖 1-6，直接索引；越界取顶档。"""
        for row in stars:
            if row.star == star:
                return row
        return stars[-1]  # 越界（如 star=7）取顶档
