"""M5 L1.5 面板装配引擎：PlayerState -> 三轴结算面板（dps/ehp/burst）。

budget: 决策侧 <5ms/次（122 弈子查表 + Counter 归并 + 断点乘区）。
红线自查：零网络、零输入模拟、零进程读取。

设计（阶段2技术方案 §3.3）：
- 单子能量沿用 power_score 口径 (hp + 10*ad)/1000，装备按 grade 增益放大
- 羁绊乘区用 M4 断点表 breakpoint_weight（真实断点替代 M3 激活数近似）
- 归一基准 = 全库 star3 平均能量 x 10 格（与 PowerScorer._board_max 同口径）
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from tft_copilot.decision.snapshot import PlayerState, UnitOnBoard
from tft_copilot.knowledge.equips_loader import EquipsBook
from tft_copilot.knowledge.traits_loader import TraitsBook, TraitsDataError
from tft_copilot.knowledge.units_loader import KnowledgeError, UnitsBook

# 单子能量口径（与 power_score 一致，勿单边修改）
UNIT_POWER_DIV = 1000.0
UNIT_POWER_AD_MULT = 10.0
BOARD_SIZE = 10
# 装备增益系数：dps 侧按 grade x0.10、ehp 侧按 grade x0.06 线性放大单子能量
ITEM_DPS_MULT = 0.10
ITEM_EHP_MULT = 0.06
# 羁绊断点乘区系数：断点权重 0-1 -> dps x(1+0.08w) / ehp x(1+0.06w)
TRAIT_DPS_MULT = 0.08
TRAIT_EHP_MULT = 0.06
# 爆发系数：蓝条缺口 <=40 视为高爆发（低费快启动型），能量 x1.2
BURST_MANA_TH = 40
BURST_BONUS = 1.2
# 感知置信度阈值（与 snapshot.UNIT_SCORE_TH 对齐）
SCORE_TH = 0.45
# 三轴归一上限
AXIS_CAP = 100.0


@dataclass(frozen=True)
class PanelScores:
    """结算面板三轴（0-100）。burst 反映快启动能力（技能频率×能量）。"""

    dps: float
    ehp: float
    burst: float


class PanelEngine:
    """装配一家 PlayerState 的三轴面板。units=None 返回 None（E6 诚实）。"""

    def __init__(
        self,
        units_book: UnitsBook,
        traits_book: TraitsBook,
        equips_book: EquipsBook | None = None,
    ) -> None:
        self._units = units_book
        self._traits = traits_book
        self._equips = equips_book
        # 满配基准：全库 star==3 行平均能量 x 10 格（与 PowerScorer 同口径）
        rows = [r for u in units_book for r in u.stars if r.star == 3]
        avg = (
            sum((r.hp + UNIT_POWER_AD_MULT * r.ad) / UNIT_POWER_DIV for r in rows)
            / len(rows)
            if rows
            else 1.0
        )
        self._board_max = BOARD_SIZE * max(avg, 1e-6)

    # ---------- 主入口 ----------

    def assemble(self, state: PlayerState) -> PanelScores | None:
        """装配三轴；units 未侦查返回 None（不猜）。"""
        if state.units is None:
            return None
        units = [u for u in state.units if u.score >= SCORE_TH]
        dps = ehp = burst = 0.0
        trait_counts: Counter[str] = Counter()
        for u in units:
            try:
                unit = self._units.get_unit(u.unit_id)
            except KnowledgeError:
                continue  # 未知棋子诚实跳过
            star = u.star if u.star is not None else 1
            row = self._pick_row(unit.stars, star)
            base = (row.hp + UNIT_POWER_AD_MULT * row.ad) / UNIT_POWER_DIV
            item_grade = self._item_grade(u)
            dps += base * (1.0 + ITEM_DPS_MULT * item_grade)
            ehp += base * (1.0 + ITEM_EHP_MULT * item_grade)
            mana_gap = getattr(unit, "mana_max", 0) or 0
            mana_start = getattr(unit, "mana_start", 0) or 0
            gap = mana_gap - mana_start
            burst += base * (BURST_BONUS if gap <= BURST_MANA_TH else 1.0)
            for t in unit.traits:
                trait_counts[t] += 1
        # 羁绊断点乘区（M4 断点表替代激活数近似）
        dps_mult = ehp_mult = 1.0
        for tname, active in trait_counts.items():
            w = self._trait_weight(tname, active)
            if w > 0:
                dps_mult *= 1.0 + TRAIT_DPS_MULT * w
                ehp_mult *= 1.0 + TRAIT_EHP_MULT * w
        dps = min(dps * dps_mult / self._board_max * AXIS_CAP, AXIS_CAP)
        ehp = min(ehp * ehp_mult / self._board_max * AXIS_CAP, AXIS_CAP)
        burst = min(burst / self._board_max * AXIS_CAP, AXIS_CAP)
        return PanelScores(round(dps, 1), round(ehp, 1), round(burst, 1))

    # ---------- 内部 ----------

    def _item_grade(self, u: UnitOnBoard) -> float:
        """该弈子装备 grade 总和；equips 库未注入或 id 未知按 0（降级不炸）。"""
        if self._equips is None or not u.items:
            return 0.0
        total = 0.0
        for eid in u.items:
            try:
                total += self._equips.by_id(int(eid)).grade
            except Exception:
                continue  # 未知装备 id / 非法值：诚实跳过（降级不炸）
        return total

    def _trait_weight(self, tname: str, active: int) -> float:
        """羁绊断点权重；未知羁绊（名称不匹配）返回 0。"""
        try:
            return self._traits.by_name(tname).breakpoint_weight(active)
        except TraitsDataError:
            return 0.0
    @staticmethod
    def _pick_row(stars: tuple, star: int) -> object:
        """按目标星级选行；越界取顶档（与 PowerScorer._pick_row 同规则）。"""
        for row in stars:
            if row.star == star:
                return row
        return stars[-1]
