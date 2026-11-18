"""SceneScheduler：全屏锚点 → GameScene 枚举判定。

budget: 15ms/frame
设计（技术方案 D5）：优先级锚点链——每场景一个唯一性图标，
锚点模板与 anchors.json 同目录版本化，灰度匹配降低光照敏感。
"""

from __future__ import annotations

from enum import Enum

import cv2
import numpy as np

from tft_copilot.perception.templates import TemplateBank


class GameScene(Enum):
    SHOP = "shop"            # 选牌/备战（商店可见）
    BATTLE = "battle"        # 战斗阶段
    PRE_GAME = "pre_game"    # 局前界面
    POST_GAME = "post_game"  # 局后结算
    DRAFT = "draft"          # 选秀
    LOBBY = "lobby"          # 大厅
    DORM = "dorm"            # 宿舍/局外
    UNKNOWN = "unknown"      # 兜底


# 判定链顺序 = 优先级（前面的先判）
DETECT_ORDER: list[GameScene] = [GameScene.SHOP, GameScene.BATTLE, GameScene.PRE_GAME]
# 阈值标定依据：合成帧对角线分 ≥0.91，最大交叉分 0.762（shop锚点被battle/pre_game帧误配）
# 取两者之间安全值 0.82；真机标定后由 M6 重新校准
SCORE_TH = 0.82


def _match_score(frame: np.ndarray, template: np.ndarray) -> float:
    """灰度+高斯模糊预处理后匹配（抗噪声/光照，TM_CCOEFF_NORMED）。"""
    g1 = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    g2 = cv2.GaussianBlur(cv2.cvtColor(template, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    res = cv2.matchTemplate(g1, g2, cv2.TM_CCOEFF_NORMED)
    return float(res.max())


class SceneScheduler:
    """场景判定：合成帧锚点 = anchors.json 中的色块+文字。"""

    def __init__(self, bank: TemplateBank | None = None) -> None:
        # bank 参数保留（未来真机模板从 bank 加载）；M2 锚点模板由 scene_anchors 合成
        self._bank = bank
        from tft_copilot.perception.scene_anchors import build_anchor_templates
        self._anchor_templates = build_anchor_templates()  # {scene_name: ndarray}

    def detect(self, frame: np.ndarray) -> GameScene:
        """单帧场景判定。"""
        for scene in DETECT_ORDER:
            tpl = self._anchor_templates.get(scene.value)
            if tpl is None:
                continue
            score = _match_score(frame, tpl)
            if score >= SCORE_TH:
                return scene
        return GameScene.UNKNOWN

    def poll_interval(self, scene: GameScene) -> float:
        """场景降频策略（秒）。"""
        table = {
            GameScene.SHOP: 0.2,      # 5Hz
            GameScene.BATTLE: 1.0,    # 1Hz
            GameScene.PRE_GAME: 2.0,  # 0.5Hz
            GameScene.POST_GAME: 2.0,
            GameScene.DRAFT: 0.2,
            GameScene.LOBBY: 2.0,
            GameScene.DORM: 2.0,
            GameScene.UNKNOWN: 1.0,
        }
        return table[scene]
