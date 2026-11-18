"""锚点模板生成：anchors.json ROI + 标准绘制参数 → 场景锚点模板。

合成帧引擎与 SceneScheduler 共享本模块的绘制函数，
保证"画进帧里的"与"拿来匹配的"逐像素一致（自洽闭环）。
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "data" / "templates" / "v18.6"
ANCHORS_PATH = TEMPLATE_DIR / "anchors.json"

# 场景锚点外观：BGR 色块 + 场景名白字（合成基准，M6 换真机截图）
SCENE_ANCHOR_STYLE: dict[str, tuple[int, int, int]] = {
    "shop": (180, 90, 40),
    "battle": (90, 90, 220),
    "pre_game": (90, 200, 90),
}

SCENE_ANCHOR_KEYS: dict[str, str] = {
    "shop": "refresh_btn",
    "battle": "battle_banner",
    "pre_game": "lobby_play",
}


def load_anchor_config() -> dict:
    return json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))


def draw_scene_anchor(frame: np.ndarray, scene: str) -> None:
    """把场景锚点画进全帧（供合成帧引擎复用）。"""
    cfg = load_anchor_config()
    key = SCENE_ANCHOR_KEYS.get(scene)
    if key is None:
        return
    x, y, w, h = cfg["scenes"][scene]["anchors"][key]
    frame[y : y + h, x : x + w] = SCENE_ANCHOR_STYLE.get(scene, (128, 128, 128))
    cv2.putText(frame, scene.upper(), (x + 10, y + h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)


def build_anchor_templates() -> dict[str, np.ndarray]:
    """生成 3 个场景锚点模板（在空白画布上绘制后裁剪 ROI）。"""
    cfg = load_anchor_config()
    templates: dict[str, np.ndarray] = {}
    for scene, key in SCENE_ANCHOR_KEYS.items():
        x, y, w, h = cfg["scenes"][scene]["anchors"][key]
        canvas = np.zeros((1080, 1920, 3), dtype=np.uint8)
        draw_scene_anchor(canvas, scene)
        templates[scene] = canvas[y : y + h, x : x + w].copy()
    return templates
