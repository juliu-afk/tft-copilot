"""决策层包导出。

红线自查：零网络、零输入模拟、零进程读取。
"""

from tft_copilot.decision.engine import DecisionEngine
from tft_copilot.decision.layer_progress import MILESTONES, LayerProgress
from tft_copilot.decision.matchup import MatchupPrediction, advice_for, predict
from tft_copilot.decision.power_score import PowerScorer
from tft_copilot.decision.snapshot import (
    Advice,
    BoardSnapshot,
    LayersGuard,
    PlayerState,
    TaskState,
    UnitOnBoard,
    quality_gate,
)

__all__ = [
    "Advice",
    "BoardSnapshot",
    "DecisionEngine",
    "LayerProgress",
    "LayersGuard",
    "MILESTONES",
    "MatchupPrediction",
    "PlayerState",
    "PowerScorer",
    "TaskState",
    "UnitOnBoard",
    "advice_for",
    "predict",
    "quality_gate",
]
