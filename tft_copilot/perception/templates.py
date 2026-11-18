"""TemplateBank：感知模板库管理（头像/数字/角标，版本目录三重校验）.

budget: 10ms/frame（加载时 LUT 预计算，运行时零重复计算）
红线自查：纯本地图像文件消费，零网络。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "data" / "templates"
DEFAULT_PATCH = "18.6"

# 数字颜色池（BGR）：白/黄/金/红/蓝
NUMBER_COLORS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "yellow": (90, 220, 240),
    "gold": (60, 200, 240),
    "red": (80, 80, 240),
    "blue": (230, 170, 80),
}


def _font_digit_template(digit: int, color: tuple[int, int, int], size: int = 28) -> np.ndarray:
    """程序绘制数字模板（与合成帧同一绘制参数，保证匹配成功）。

    canvas 40x40：ROI 高 50px，模板必须 < ROI 才能匹配。
    """
    canvas = np.full((40, 40, 3), (35, 35, 40), dtype=np.uint8)
    text = str(digit)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.3, 3)
    cv2.putText(canvas, text, ((canvas.shape[1] - tw) // 2, (canvas.shape[0] + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3, cv2.LINE_AA)
    return canvas


def _roman_star_template(star: int, size: int = 32) -> np.ndarray:
    """程序绘制星级角标模板：罗马数字 I/II/III，1/2星银色、3星金色。"""
    canvas = np.full((size, size * 2, 3), (28, 28, 32), dtype=np.uint8)
    romans = {1: "I", 2: "II", 3: "III"}
    color = (200, 200, 220) if star < 3 else (80, 200, 255)
    cv2.putText(canvas, romans[star], (4, size - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
    return canvas


@dataclass(frozen=True)
class Template:
    kind: str  # portrait / digit / star
    key: str   # unit_id / "digit_3_white" / "star_2"
    image: np.ndarray  # BGR


class TemplateBank:
    """模板库：portraits + digits + stars，按版本目录隔离。"""

    def __init__(self, patch: str = DEFAULT_PATCH, load_portraits: bool = True, load_digits: bool = True, load_stars: bool = True) -> None:
        self.patch = patch
        self.dir = TEMPLATES_DIR / f"v{patch}"
        if not self.dir.is_dir():
            raise FileNotFoundError(f"模板目录不存在: {self.dir}")
        anchors_file = self.dir / "anchors.json"
        if not anchors_file.is_file():
            raise FileNotFoundError(f"anchors.json 缺失: {anchors_file}")
        meta = json.loads(anchors_file.read_text(encoding="utf-8"))
        if meta.get("meta", {}).get("patch") != patch:
            raise ValueError(f"三重校验失败：anchors.json patch={meta.get('meta', {}).get('patch')} != {patch}")
        self._portraits: dict[str, np.ndarray] = {}
        self._digits: dict[str, np.ndarray] = {}
        self._stars: dict[str, np.ndarray] = {}
        if load_portraits:
            self._load_portraits()
        if load_digits:
            self._load_digits()
        if load_stars:
            self._load_stars()

    def _load_portraits(self) -> None:
        pdir = self.dir / "portraits"
        for f in sorted(pdir.glob("*.png")):
            img = cv2.imread(str(f))
            if img is not None:
                self._portraits[f.stem] = img

    def _load_digits(self) -> None:
        for name, color in NUMBER_COLORS.items():
            for d in range(10):
                key = f"digit_{d}_{name}"
                self._digits[key] = _font_digit_template(d, color)

    def _load_stars(self) -> None:
        for s in (1, 2, 3):
            self._stars[f"star_{s}"] = _roman_star_template(s)

    @property
    def portraits(self) -> dict[str, np.ndarray]:
        return self._portraits

    @property
    def digits(self) -> dict[str, np.ndarray]:
        return self._digits

    @property
    def stars(self) -> dict[str, np.ndarray]:
        return self._stars

    def portrait_count(self) -> int:
        return len(self._portraits)
