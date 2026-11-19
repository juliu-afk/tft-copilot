"""WinOCR 数字识别器：PowerShell 调 Windows 内置 WinRT OCR（M6 真机层）。

零三方依赖：winsdk 在 Py3.14 无预编译包，改用 powershell.exe -File 子进程调用，
输出 WORD|text|x|y|w|h 行协议。zh-CN OCR 语言包系统自带。

数字读取策略：右栏面板 4x 放大 -> OCR -> 按锚点 ROI 过滤 + 数值范围校验。
budget: ~200ms/次（子进程开销，分频调用：每回合读一次而非每帧）。
红线自查：只读屏幕像素，无输入模拟。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

import sys

def _ps1_path() -> Path:
    """ocr_probe.ps1 位置：frozen 走 _MEIPASS/tools，源码走项目根/tools。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "tools" / "ocr_probe.ps1"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / "tools" / "ocr_probe.ps1"

_OCR_PS = _ps1_path()
_SCALE = 4
_PANEL = (1690, 60, 230, 940)  # 右栏面板 (x, y, w, h)


def _run_ocr_ps(img_path: Path) -> list[tuple[str, int, int, int, int]]:
    """跑一次 PowerShell OCR，返回 (text, x, y, w, h) 列表（图内坐标）。"""
    out_file = img_path.with_suffix(".txt")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(_OCR_PS), "-path", str(img_path), "-out", str(out_file)],
        capture_output=True, timeout=30,
    )
    if not out_file.exists():
        return []
    words = []
    for line in out_file.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("WORD|"):
            parts = line.split("|")
            if len(parts) == 6:
                words.append((parts[1], *[int(p) for p in parts[2:]]))
    return words


def ocr_words(frame: np.ndarray, roi: tuple[int, int, int, int] | None = None) -> list[tuple[str, int, int, int, int]]:
    """对 frame 的 ROI 做 4x 放大 OCR，返回全帧坐标的 (text,x,y,w,h)。"""
    px, py, pw, ph = roi or _PANEL
    panel = frame[py:py + ph, px:px + pw]
    big = cv2.resize(panel, None, fx=_SCALE, fy=_SCALE, interpolation=cv2.INTER_CUBIC)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "ocr.png"
        cv2.imwrite(str(tmp), big)
        words = _run_ocr_ps(tmp)
    return [(t, px + x // _SCALE, py + y // _SCALE, w // _SCALE, h // _SCALE)
            for t, x, y, w, h in words]


# 真机标定锚点（2026-11-19 实测：三帧时序稳定验证）
# gold: (1750,655) 单字符金币数字
# hp:   (1810,914) 右下角大号血量数字
_GOLD_ROI = (1738, 645, 70, 40)
_HP_ROI = (1785, 900, 90, 45)
_LEVEL_ROI = (1798, 74, 120, 36)  # 顶部等级区（1/75 等）
LAYER_ROI = (1785, 900, 90, 45)   # 层数与血量同区右下，待分离校准


def read_gold(frame: np.ndarray) -> int | None:
    """金币：右栏中部金色数字。"""
    for t, x, y, w, h in ocr_words(frame):
        if x >= _GOLD_ROI[0] - 15 and abs(y - _GOLD_ROI[1]) < 15 and t.isdigit():
            return int(t)
    return None


def read_hp(frame: np.ndarray) -> int | None:
    """血量：右下角大数字。"""
    for t, x, y, w, h in ocr_words(frame):
        if x >= _HP_ROI[0] - 15 and abs(y - _HP_ROI[1]) < 15 and t.isdigit():
            return int(t)
    return None


def read_level(frame: np.ndarray) -> int | None:
    """等级：顶部白字（小于等于 10）。"""
    best = None
    for t, x, y, w, h in ocr_words(frame):
        if _LEVEL_ROI[0] - 15 <= x and abs(y - _LEVEL_ROI[1]) < 15 and t.isdigit():
            v = int(t)
            if v <= 10:
                best = v if best is None else max(best, v)
    return best


def read_numbers_ocr(frame: np.ndarray) -> dict[str, int | None]:
    """读四数字：layer/gold/hp/level（layer 与 hp 同区待分离，暂同 hp）。"""
    words = ocr_words(frame)
    out = {"layer": None, "gold": None, "hp": None, "level": None}
    for t, x, y, w, h in words:
        if not t.isdigit():
            continue
        v = int(t)
        if abs(y - 655) < 15 and x >= 1735:
            out["gold"] = v
        elif y >= 900:
            out["hp"] = v
        elif abs(y - 84) < 15 and x >= 1790 and v <= 10:
            out["level"] = v
    out["layer"] = out["hp"]  # 临时：层数待独立锚点
    return out
