"""M2 合成帧引擎：用真实头像 + 程序绘制 UI 生成基准帧。

设计原则（技术方案 D1）：识别算法第一公民是 ndarray(BGR)，
合成帧与 mss 真实帧同一数据接口，CI 无显示器环境可跑全量测试。

本模块仅测试/CLI 使用，不进主包运行时依赖。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "data" / "templates" / "v18.6"
ANCHORS_PATH = TEMPLATE_DIR / "anchors.json"
PORTRAITS_DIR = TEMPLATE_DIR / "portraits"

# 8 场景枚举（与 scene.py 共享字面量）
SCENES = ["shop", "battle", "pre_game", "lobby", "post_game", "draft", "dorm", "unknown"]
# 场景→锚点映射（合成帧与 scene.py 使用同一份 anchors.json）
SCENE_ANCHOR_KEYS = {
    "shop": "refresh_btn",
    "battle": "battle_banner",
    "pre_game": "lobby_play",
}


@dataclass(frozen=True)
class SynthConfig:
    seed: int = 42
    noise_sigma: float = 6.0
    brightness_jitter: float = 0.12
    scale_jitter: float = 0.08


def load_anchors() -> dict:
    return json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))


def available_portraits() -> list[Path]:
    return sorted(PORTRAITS_DIR.glob("*.png"))


def _draw_text_badge(frame: np.ndarray, text: str, xy: tuple[int, int], scale: float, color, thickness: int = 2) -> None:
    cv2.putText(frame, text, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def _paste_portrait(frame: np.ndarray, img: np.ndarray, x: int, y: int, w: int, h: int) -> None:
    """原尺寸居中贴放（M2 合成基准：模板与帧内头像同尺寸 1:1）。

    真机中头像缩放差异由 UnitSpotter 多尺度金字塔兜底（0.6-1.4）。
    """
    ih, iw = img.shape[:2]
    ox, oy = x + (w - iw) // 2, y + (h - ih) // 2
    frame[oy : oy + ih, ox : ox + iw] = img


def _add_noise(frame: np.ndarray, rng: np.random.Generator, sigma: float) -> None:
    if sigma <= 0:
        return
    noise = rng.normal(0, sigma, frame.shape).astype(np.float32)
    frame[:] = np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def _add_brightness(frame: np.ndarray, rng: np.random.Generator, jitter: float) -> None:
    if jitter <= 0:
        return
    factor = 1.0 + rng.uniform(-jitter, jitter)
    frame[:] = np.clip(frame.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def _draw_scene_anchor(frame: np.ndarray, scene: str, anchors: dict) -> None:
    """按场景绘制对应锚点（合成帧基准：模板库内 anchors.json 的坐标）。"""
    key = SCENE_ANCHOR_KEYS.get(scene)
    if key is None:
        return
    scene_cfg = anchors["scenes"][scene]["anchors"][key]
    x, y, w, h = scene_cfg
    color = {"shop": (180, 90, 40), "battle": (90, 90, 220), "pre_game": (90, 200, 90)}.get(scene, (128, 128, 128))
    overlay = frame[y : y + h, x : x + w]
    overlay[:] = color
    _draw_text_badge(frame, scene.upper(), (x + 10, y + h // 2), 0.7, (255, 255, 255))


def draw_number(frame: np.ndarray, text: str, roi: tuple[int, int, int, int], color) -> None:
    """在 ROI 内画数字（白色描边，模拟 TFT UI 数字）。"""
    x, y, w, h = roi
    sub = frame[y : y + h, x : x + w]
    sub[:] = (35, 35, 40)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.3, 3)
    cv2.putText(sub, text, ((w - tw) // 2, (h + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3, cv2.LINE_AA)


def synth_scene_frame(
    scene: str,
    layer: int = 10,
    gold: int = 20,
    hp: int = 100,
    level: int = 7,
    portraits: list[Path] | None = None,
    config: SynthConfig | None = None,
) -> np.ndarray:
    """生成一个合成帧（1920x1080 BGR）。场景锚点 + 4 数字 + 商店/备战头像。"""
    cfg = config or SynthConfig()
    rng = np.random.default_rng(cfg.seed)
    anchors = load_anchors()
    frame = np.full((1080, 1920, 3), (28, 28, 32), dtype=np.uint8)
    portrait_imgs = portraits or available_portraits()

    # 场景锚点
    _draw_scene_anchor(frame, scene, anchors)

    # 数字 ROI
    num_cfg = anchors["numbers"]
    draw_number(frame, str(layer), tuple(num_cfg["layer"]["roi"]), (255, 255, 255))
    draw_number(frame, str(gold), tuple(num_cfg["gold"]["roi"]), (60, 215, 245))
    draw_number(frame, str(hp), tuple(num_cfg["hp"]["roi"]), (80, 170, 250))
    draw_number(frame, str(level), tuple(num_cfg["level"]["roi"]), (255, 255, 255))

    # 商店五卡（shop 场景才有）
    if scene == "shop" and portrait_imgs:
        shop5 = anchors["units"]["shop5"]["rois"]
        for i, roi in enumerate(shop5):
            img = cv2.imread(str(portrait_imgs[i % len(portrait_imgs)]))
            if img is not None:
                _paste_portrait(frame, img, *roi)

    # 备战席（非 battle 场景）
    if scene != "battle" and portrait_imgs:
        bench = anchors["units"]["bench"]["rois"]
        for i, roi in enumerate(bench[:5]):
            img = cv2.imread(str(portrait_imgs[i % len(portrait_imgs)]))
            if img is not None:
                _paste_portrait(frame, img, *roi)

    _add_noise(frame, rng, cfg.noise_sigma)
    _add_brightness(frame, rng, cfg.brightness_jitter)
    return frame
