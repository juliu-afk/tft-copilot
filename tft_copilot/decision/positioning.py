"""M5 站位粗算：range 分层 + 前后排启发式 -> 站位档位与修正系数。

budget: 决策侧 <1ms/次（纯 Counter 归并）。
红线自查：零网络、零输入模拟、零进程读取。

格位定义（阶段2方案 §3.5）：0-27 线性编号，0-7 前两排 / 8-15 中排 / 16-27 后排。
positions 缺失时按 range 推断：近战(range 1-3)默认前排、远程(range>=4)默认后排。
"""

from __future__ import annotations

from dataclasses import dataclass

from tft_copilot.decision.snapshot import PlayerState
from tft_copilot.knowledge.units_loader import KnowledgeError, UnitsBook

# 感知置信度阈值（与 snapshot.UNIT_SCORE_TH 对齐）
SCORE_TH = 0.45
# 近战/远程分界：range<=3 视为近战侧（range 2-3 罕见，归近战）
MELEE_RANGE_MAX = 3
# 前两排格位范围
FRONT_MAX = 8
# 站位档位阈值：前排占比 >=0.6 aggressive / <=0.3 defensive / 其余 standard
AGGRESSIVE_TH = 0.60
DEFENSIVE_TH = 0.30
# 修正系数界（进 predict_l15 的 diff 修正项）
PENALTY_RUSHED = -5.0  # 后排暴露被冲脸
BONUS_PRESSURE = 2.0  # 顶前压制
# 对方近战数阈值：>=4 视为冲脸阵容
OPP_MELEE_TH = 4
# 我方远程数阈值：>=4 视为后排依赖阵容
MY_RANGED_TH = 4


@dataclass(frozen=True)
class PositionContext:
    """站位上下文。my_front_ratio: 前排占比 0-1。"""

    my_front_ratio: float
    my_ranged_count: int
    opp_melee_count: int
    tier: str  # aggressive | standard | defensive


def classify(state: PlayerState, book: UnitsBook) -> PositionContext | None:
    """一家 PlayerState -> PositionContext；units=None 返回 None（不猜）。"""
    if state.units is None:
        return None
    units = [u for u in state.units if u.score >= SCORE_TH]
    if not units:
        return None
    front_n = ranged_n = melee_n = 0
    for u in units:
        try:
            unit = book.get_unit(u.unit_id)
        except KnowledgeError:
            continue
        is_ranged = unit.range >= MELEE_RANGE_MAX + 1
        if is_ranged:
            ranged_n += 1
        else:
            melee_n += 1
        # positions 有值按格位判前排；无值按 range 推断（近战=前排）
        if state.positions is not None:
            pos = state.positions.get(u.unit_id)
            front = pos is not None and pos < FRONT_MAX
        else:
            front = not is_ranged
        if front:
            front_n += 1
    ratio = front_n / len(units)
    if ratio >= AGGRESSIVE_TH:
        tier = "aggressive"
    elif ratio <= DEFENSIVE_TH:
        tier = "defensive"
    else:
        tier = "standard"
    return PositionContext(round(ratio, 2), ranged_n, melee_n, tier)


def pos_penalty(my_ctx: PositionContext | None, opp_ctx: PositionContext | None) -> float:
    """站位修正系数：-5.0 .. +2.0。任一侧 None 返回 0（降级不炸）。

    WHY（阶段2方案 §3.5）：
    - 沉底(defensive) + 我方后排依赖 + 对方冲脸多 -> 被切后排，-5
    - 顶前(aggressive) + 对方近战少 -> 压制对方远程，+2
    """
    if my_ctx is None or opp_ctx is None:
        return 0.0
    if (
        my_ctx.tier == "defensive"
        and my_ctx.my_ranged_count >= MY_RANGED_TH
        and opp_ctx.opp_melee_count >= OPP_MELEE_TH
    ):
        return PENALTY_RUSHED
    if my_ctx.tier == "aggressive" and opp_ctx.opp_melee_count < OPP_MELEE_TH:
        return BONUS_PRESSURE
    return 0.0
