"""卡组参谋包（M4）。红线自查：零网络、零输入模拟、零进程读取。"""

from tft_copilot.deck.combo_scorer import ComboScorer, DeckCombo, score_combo
from tft_copilot.deck.recommender import DeckRecommender, RecommendResult, build_phase_notes

__all__ = [
    "ComboScorer",
    "DeckCombo",
    "DeckRecommender",
    "RecommendResult",
    "build_phase_notes",
    "score_combo",
]
