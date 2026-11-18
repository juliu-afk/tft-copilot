"""模块(1) 层数进度：里程碑预警 + 达标即停（工程方案 5.1）。

budget: 决策侧 <1ms/次（纯查表）。
红线自查：零网络、零输入模拟、零进程读取。
"""

from __future__ import annotations

from tft_copilot.decision.snapshot import Advice

# 关键层数节点（工程方案 5.1 原表）
MILESTONES: tuple[int, ...] = (10, 25, 50, 100, 200, 300, 400, 500, 625, 1000, 1250)
# 达标即停：500 分水岭 + 岩宝（工程方案 5.1）
STOP_LAYERS = 500
STOP_HP = 40


def _reward_text(rewards_by_layers: dict[int, str], n: int) -> str | None:
    """奖励文案；无对应档返回 None。"""
    return rewards_by_layers.get(n)


class LayerProgress:
    """层数进度规则引擎。

    once 去重：fired 集合按 match 生命周期，同一里程碑只触发一次。
    """

    def __init__(self, rewards_by_layers: dict[int, str]) -> None:
        # rewards_by_layers: {layers: "选项1 / 选项2"}，来自 rules.rewards
        self._rewards = rewards_by_layers
        self._fired: set[str] = set()

    def _fire_once(self, key: str, advice: Advice) -> Advice | None:
        if key in self._fired:
            return None
        self._fired.add(key)
        return advice

    def on_layers(
        self, layers: int | None, hp: int | None
    ) -> list[Advice]:
        """输入当前层数/血量，输出建议列表。"""
        if layers is None:
            return []
        out: list[Advice] = []
        for n in MILESTONES:
            # R-milestone-pre：进入里程碑前 1 层
            if layers == n - 1:
                rw = _reward_text(self._rewards, n)
                if rw is not None:
                    adv = self._fire_once(
                        f"pre:{n}",
                        Advice("info", f"下一档奖励：{rw}，还差 1 层", "layer_progress"),
                    )
                    if adv:
                        out.append(adv)
                else:
                    adv = self._fire_once(
                        f"pre:{n}",
                        Advice("info", f"下一档：{n} 层，还差 1 层", "layer_progress"),
                    )
                    if adv:
                        out.append(adv)
            # R-milestone-hit：达成里程碑
            if layers == n:
                rw = _reward_text(self._rewards, n)
                if rw is not None:
                    adv = self._fire_once(
                        f"hit:{n}",
                        Advice("info", f"达成 {n} 层档：{rw}", "layer_progress"),
                    )
                    if adv:
                        out.append(adv)
                else:
                    adv = self._fire_once(
                        f"hit:{n}",
                        Advice("info", f"达成 {n} 层", "layer_progress"),
                    )
                    if adv:
                        out.append(adv)
        # R-stop：达标即停
        if layers >= STOP_LAYERS and (hp is not None and hp < STOP_HP):
            adv = self._fire_once(
                "stop",
                Advice(
                    "critical",
                    "已到 500 层分水岭+岩宝，超级时间挑战达标即停，别贪",
                    "layer_progress",
                ),
            )
            if adv:
                out.append(adv)
        return out


def build_rewards_map(rewards: list) -> dict[int, str]:
    """把 rules_loader.Reward 列表转成 {layers: 文案}。

    WHY: 决策层只消费 dict，避免在规则热路径上反复解包 dataclass。
    """
    m: dict[int, str] = {}
    for r in rewards:
        m[int(r.layers)] = " / ".join(r.options)
    return m
