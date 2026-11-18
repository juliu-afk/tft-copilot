"""模块(4) 影响推演：胜负对任务/层数/血量/名次四路交叉（工程方案 5.4）。

budget: 决策侧 <0.1ms/次（纯查表）。
红线自查：零网络、零输入模拟、零进程读取。
"""

from __future__ import annotations

from tft_copilot.decision.matchup import MatchupPrediction
from tft_copilot.decision.snapshot import Advice, TaskState

# 碎片提示距离：距下一奖励档 <=5 层时提示（工程方案 5.4 层数路）
FRAGMENT_HINT_DIST = 5


def evaluate(
    pred: MatchupPrediction,
    task: TaskState | None,
    layers: int | None,
    next_reward_layers: int | None,
    next_reward_options: str | None,
) -> list[Advice]:
    """四路交叉推演。

    参数:
        pred: 对位预测（含 winrate/tier/confidence）
        task: 任务状态；None = 感知未覆盖任务图标（E5 降级：只出层数路）
        layers: 当前层数
        next_reward_layers/options: 下一奖励档及内容（rules.rewards 查询）
    """
    out: list[Advice] = []

    # ---- 路A：任务断连/连败保连（任务 x 胜负）----
    if task is not None and pred.tier in ("high", "low"):
        pct = round((pred.winrate or 0.5) * 100)
        if task.streak_type == "win" and pred.tier == "low":
            # 连胜任务进行中，下回合预测输 -> 断连风险（工程方案 5.1 R-断连）
            out.append(
                Advice(
                    "warn",
                    f"连胜任务第{task.streak_count}场，预测胜率 {pct}%，断连风险高——考虑提前放弃此任务止损",
                    "impact",
                )
            )
        elif task.streak_type == "lose" and pred.tier == "high":
            # 连败任务进行中，下回合预测赢 -> 连败断
            out.append(
                Advice(
                    "critical",
                    f"连败任务第{task.streak_count}场，预测胜率 {pct}%——连败要断，需主动控血故意输",
                    "impact",
                )
            )
        elif task.streak_type == "lose" and pred.tier == "low":
            # 连败任务 + 预测输 = 正合连败流（掉层保血）
            out.append(
                Advice(
                    "info",
                    f"连败任务第{task.streak_count}场，预测输——连败保住+掉层养血，正合连败流",
                    "impact",
                )
            )

    # ---- 路B：层数路（碎片/奖励档）----
    if layers is not None and next_reward_layers is not None:
        dist = next_reward_layers - layers
        if 0 < dist <= FRAGMENT_HINT_DIST:
            opts = next_reward_options or "奖励"
            out.append(
                Advice(
                    "info",
                    f"距 {next_reward_layers} 层档（{opts}）还差 {dist} 层",
                    "impact",
                )
            )

    # ---- 路C：血量路（连败保血公式）----
    # 工程方案 5.4 典型：低胜率时提示卖血——已由 matchup 模块承担（advice_for），
    # 此处不重复；血量告急独立规则：
    # （hp 阈值告急提示由 HUD 层按血量历史处理，M3 不做，避免文案重复）

    # ---- 路D：名次路（达标即停）----
    # 已由 layer_progress R-stop 承担（500+hp<40），此处不重复。

    return out
