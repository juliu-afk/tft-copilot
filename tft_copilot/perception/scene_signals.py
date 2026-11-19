"""真机场景识别：UI 结构信号判定（M6 真机层，替代 M2 合成模板）。

三条结构信号（1920x1080 标准帧坐标系）：
- scoreboard: 右侧10人计分板行结构 -> 对局中（shop/battle/draft 共用）
- shopstrip: 底部商店5卡槽列结构 -> 备战/选牌界面
- topbanner: 顶部回合横幅灰度方差 -> 对局顶部 UI 存在

阈值标定（2026-11-19 真机帧 vs 桌面帧实测）：
- scoreboard: 对局 42.1 / 桌面 1.4 -> 阈值 15（分离度 30x）
- shopstrip: 对局 32.5 / 桌面 9.5 -> 阈值 20（分离度 3.4x）
- topbanner: 对局 104.3 / 桌面 34.6 -> 阈值 55（分离度 3x）
红线自查：纯只读像素统计，无输入模拟。
"""

from __future__ import annotations

import cv2
import numpy as np

from tft_copilot.perception.scene import GameScene

# 信号区域（x, y, w, h）
SCOREBOARD_ROI = (1720, 100, 200, 620)
SHOPSTRIP_ROI = (300, 950, 1300, 100)
TOPBANNER_ROI = (660, 0, 600, 100)

# 阈值
TH_SCOREBOARD = 15.0
TH_SHOPSTRIP = 20.0
TH_TOPBANNER = 55.0


def _gray(frame):
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def sig_scoreboard(frame):
    """右侧计分板行结构强度（对局存在的最强信号）。"""
    x, y, w, h = SCOREBOARD_ROI
    return float(_gray(frame[y:y + h, x:x + w]).std(axis=1).mean())


def sig_shopstrip(frame):
    """底部商店卡槽列结构强度。"""
    x, y, w, h = SHOPSTRIP_ROI
    return float(_gray(frame[y:y + h, x:x + w]).std(axis=0).mean())


def sig_topbanner(frame):
    """顶部回合横幅灰度方差。"""
    x, y, w, h = TOPBANNER_ROI
    return float(_gray(frame[y:y + h, x:x + w]).std())


def scene_signal_scores(frame):
    """返回三信号得分 dict（诊断用）。"""
    return {
        "scoreboard": sig_scoreboard(frame),
        "shopstrip": sig_shopstrip(frame),
        "topbanner": sig_topbanner(frame),
    }


def detect_scene_signal(frame):
    """真机场景判定：结构信号 -> GameScene。

    判定链：
    1. scoreboard 强 -> 对局进行中；shopstrip 强 -> SHOP（备战可买牌）
    2. scoreboard 强 + shopstrip 弱 -> BATTLE 或 DRAFT（战斗画面商店收起）
    3. 全弱 -> UNKNOWN
    """
    sb = sig_scoreboard(frame)
    if sb < TH_SCOREBOARD:
        return GameScene.UNKNOWN
    # 对局中：区分 SHOP 与 BATTLE
    if sig_shopstrip(frame) >= TH_SHOPSTRIP:
        return GameScene.SHOP
    if sig_topbanner(frame) >= TH_TOPBANNER:
        return GameScene.BATTLE
    return GameScene.SHOP  # 计分板在但其余弱，保守判 SHOP
