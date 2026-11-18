"""决策层核心数据结构：快照投影 + 层数卫兵 + 质量门卫。

红线自查：零网络、零输入模拟、零进程读取。
本模块不 import 感知层任何符号（模块级隔离，PRD §7.1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 感知置信度低于此值的弈子视为 pending，不参与决策（与 M2 PENDING_TH=0.45 对齐）
UNIT_SCORE_TH = 0.45
# 感知质量低于此值时四模块进入 Silent（PRD E1）
QUALITY_TH = 0.3
# 层数单帧最大合法跳变（PRD E2）
LAYER_MAX_JUMP = 100


@dataclass(frozen=True)
class UnitOnBoard:
    """感知 UnitBox 的决策层投影（解耦：不依赖感知层类型）。"""

    unit_id: str
    cost: int
    star: int | None  # None -> 一星基线（E4）
    score: float


@dataclass
class BoardSnapshot:
    """自家回合快照：感知 -> 决策的单入口。"""

    round_no: int
    scene: str
    quality: float
    my_units: list[UnitOnBoard]
    layers: int | None
    hp: int | None
    gold: int | None
    level: int | None

    def trusted_units(self) -> list[UnitOnBoard]:
        """剔除低置信度弈子（PRD A2）。"""
        return [u for u in self.my_units if u.score >= UNIT_SCORE_TH]


@dataclass
class PlayerState:
    """全场一家（含自己）。units=None 表示未侦查（E6 诚实原则）。"""

    player: str  # 'me' | 'p1'..'p7'
    units: list[UnitOnBoard] | None
    hp: int | None
    hp_history: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class TaskState:
    """任务状态（M3 人工输入，感知识别 M4+）。"""

    streak_type: str  # 'win' | 'lose' | 'none'
    streak_count: int  # 当前连续场次


@dataclass(frozen=True)
class Advice:
    """决策输出。level: info | warn | critical | silent。"""

    level: str
    text: str
    source: str


class LayersGuard:
    """E2 层数卫兵：只接受单调递增且单帧跳变 <=100 的读数。

    WHY: 感知误读（模板匹配偶发跳变）会让里程碑模块重复触发，
    门卫保证进入决策层的层数序列物理上合法。
    """

    def __init__(self) -> None:
        self._last: int | None = None

    def track(self, new: int | None) -> int | None:
        """返回接受后的层数；非法跳变返回 None（丢弃该帧读数）。"""
        if new is None:
            return None
        if self._last is None:
            self._last = new  # 首帧任何值都接受
            return new
        delta = new - self._last
        if 0 <= delta <= LAYER_MAX_JUMP:
            self._last = new
            return new
        return None  # 负跳变或超大跳变：丢弃

    def reset(self) -> None:
        self._last = None


def quality_gate(quality: float) -> bool:
    """质量门卫：quality >= 0.3 才放行四模块（PRD E1）。"""
    return quality >= QUALITY_TH
