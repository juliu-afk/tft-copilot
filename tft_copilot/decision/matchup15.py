"""M5 L1.5 对位预测：三轴面板加权差 -> 胜率 + 档位 + 置信度 + 降级链。

budget: 决策侧 <0.1ms/次（一次 exp；面板装配在 PanelEngine 侧另计）。
红线自查：零网络、零输入模拟、零进程读取。

降级链（PRD AC2.4）：任一侧 panel None -> 用 L0 战力总分走 matchup.predict，
输出 engine="L0"；两侧面板齐 -> 三轴加权 diff -> sigmoid，engine="L1.5"。
档位/置信度阈值复用 matchup.py 常量（单一事实源，不复制魔法数）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tft_copilot.decision.matchup import (
    CONF_DIFF_HIGH,
    CONF_DIFF_LOW,
    TIER_HIGH,
    TIER_LOW,
    WR_CAP,
    WR_FLOOR,
    MatchupPrediction,
)
from tft_copilot.decision.matchup import (
    predict as predict_l0,
)
from tft_copilot.decision.panel import PanelScores
from tft_copilot.decision.positioning import PositionContext, pos_penalty

# 三轴权重（阶段2方案 §3.4 设计初值，M6 回归重估）
W_DPS, W_EHP, W_BURST = 0.45, 0.35, 0.20
# L1.5 sigmoid 陡度：与 L0 K=0.08 同量级，diff 口径为三轴 0-100 差
K15 = 0.09


@dataclass(frozen=True)
class L15Prediction:
    """L1.5 预测输出。字段与 MatchupPrediction 同名同义（advice_for 兼容）。"""

    winrate: float | None
    tier: str
    confidence: str
    engine: str  # "L1.5" | "L0"
    detail: str  # 面板差摘要（HUD/复盘用；L0 为空串）


def predict_l15(
    my_panel: PanelScores | None,
    opp_panel: PanelScores | None,
    my_power: float | None = None,
    opp_power: float | None = None,
    my_ctx: PositionContext | None = None,
    opp_ctx: PositionContext | None = None,
) -> L15Prediction:
    """L1.5 主入口；降级链见模块 docstring。"""
    if my_panel is None or opp_panel is None:
        p0 = predict_l0(my_power, opp_power)
        return L15Prediction(p0.winrate, p0.tier, p0.confidence, "L0", "")
    diff = (
        W_DPS * (my_panel.dps - opp_panel.dps)
        + W_EHP * (my_panel.ehp - opp_panel.ehp)
        + W_BURST * (my_panel.burst - opp_panel.burst)
    )
    diff += pos_penalty(my_ctx, opp_ctx)
    winrate = 1.0 / (1.0 + math.exp(-K15 * diff))
    winrate = min(max(winrate, WR_FLOOR), WR_CAP)
    if winrate >= TIER_HIGH:
        tier = "high"
    elif winrate <= TIER_LOW:
        tier = "low"
    else:
        tier = "even"
    ad = abs(diff)
    if ad >= CONF_DIFF_HIGH:
        conf = "high"
    elif ad < CONF_DIFF_LOW:
        conf = "low"
    else:
        conf = "mid"
    detail = (
        f"面板差 d_dps={my_panel.dps - opp_panel.dps:+.1f}"
        f" d_ehp={my_panel.ehp - opp_panel.ehp:+.1f}"
        f" d_burst={my_panel.burst - opp_panel.burst:+.1f}"
        f" pos={pos_penalty(my_ctx, opp_ctx):+.1f}"
    )
    return L15Prediction(round(winrate, 3), tier, conf, "L1.5", detail)


def to_matchup_pred(p: L15Prediction) -> MatchupPrediction:
    """L15Prediction -> MatchupPrediction（advice_for 等既有消费者适配）。"""
    return MatchupPrediction(p.winrate, p.tier, p.confidence)
