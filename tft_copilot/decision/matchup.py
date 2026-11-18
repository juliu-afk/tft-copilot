"""模块(3) 对位预测 L0：sigmoid 差值 + 置信度三档（工程方案 5.3 / 6.1）。

budget: 决策侧 <0.1ms/次（一次 exp）。
红线自查：零网络、零输入模拟、零进程读取。

L0 查表法说明：双方战力分差 -> sigmoid 胜率。k=0.08 初始标定
（典型分差 +-25 覆盖 12%-88% 区间），M6 用对局库回归重估。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# sigmoid 陡度（初始标定，M6 回归重估）
K = 0.08
# 胜率上下界：L0 引擎不给绝对值——留 2% 不可知区防「98% 必赢」误导（PRD 7.1 诚实原则）
WR_FLOOR, WR_CAP = 0.05, 0.95
# 三档阈值（工程方案 5.3：>=0.65 高 / 0.35-0.65 五五开 / <0.35 低）
TIER_HIGH = 0.65
TIER_LOW = 0.35
# 置信度：|diff| >= 15 高置信；任一方缺数据或 |diff| < 8 低置信
CONF_DIFF_HIGH = 15.0
CONF_DIFF_LOW = 8.0


@dataclass(frozen=True)
class MatchupPrediction:
    """对位预测结果。confidence: high | mid | low | unknown。"""

    winrate: float | None  # 0-1；None = 数据不足（E6）
    tier: str  # high | even | low | unknown
    confidence: str  # high | mid | low | unknown


def predict(my_power: float | None, opp_power: float | None) -> MatchupPrediction:
    """L0 查表法：战力分差 -> 胜率 + 档位 + 置信度。"""
    if my_power is None or opp_power is None:
        # E6：对手快照缺失（未侦查）——诚实返回 unknown，不猜
        return MatchupPrediction(None, "unknown", "unknown")
    diff = my_power - opp_power
    winrate = 1.0 / (1.0 + math.exp(-K * diff))
    winrate = min(max(winrate, WR_FLOOR), WR_CAP)  # 上下界压缩防极端值
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
    return MatchupPrediction(round(winrate, 3), tier, conf)


def advice_for(pred: MatchupPrediction, opp_player: str | None) -> list:
    """把预测转成 Advice 文案（低胜率触发卖血提示，工程方案 5.3）。"""
    from tft_copilot.decision.snapshot import Advice  # 局部 import 防循环

    if pred.winrate is None:
        return []  # unknown 不出文案（HUD 显示问号由 HUD 层处理）
    out = []
    pct = round(pred.winrate * 100)
    opp = opp_player or "对手"
    if pred.tier == "low":
        out.append(
            Advice(
                "critical",
                f"预测胜率 {pct}% vs {opp}——建议卖血养层数，别追质量",
                "matchup",
            )
        )
    elif pred.tier == "high":
        out.append(
            Advice("info", f"预测胜率 {pct}% vs {opp}——可激进拿质量", "matchup")
        )
    return out  # even 档留给人决策（工程方案 5.3 五五开原则）
