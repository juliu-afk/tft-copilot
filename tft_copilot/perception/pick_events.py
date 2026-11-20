# -*- coding: utf-8 -*-
"""选前事件检测（M6.5，2026-11-20）：OCR 关键词识别选秀/强化符文画面.

原理：选秀/强化符文画面顶部中央有大字标题（"选秀""强化符文""选择你的XX"），
全帧 OCR 太贵，只扫顶部横幅带（y 0-160）+ 5s 节流，关键词命中即报事件。

红线自查：只读屏幕像素，无输入模拟。
"""
from __future__ import annotations

import re
import time

import numpy as np

from tft_copilot.perception.ocr_numbers import _run_ocr_ps

import cv2
import tempfile
from pathlib import Path

# 顶部横幅扫描带（选秀/符文标题区）
BANNER_ROI = (400, 0, 1120, 170)

# 事件关键词表（命中任一即报事件）
_DRAFT_KW = ("选秀",)
_HEX_KW = ("强化符文", "符文三选", "选择你的强化")

# 节流：同事件 60s 内不重报（选秀一轮一次、符文一阶段一次）
EVENT_COOLDOWN = 60.0


def detect_pick_event(frame: np.ndarray) -> str | None:
    """扫顶部横幅关键词，返回 'draft' / 'hex' / None。"""
    x, y, w, h = BANNER_ROI
    banner = frame[y:y + h, x:x + w]
    big = cv2.resize(banner, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "banner.png"
        cv2.imwrite(str(tmp), big)
        words = _run_ocr_ps(tmp)
    text = "".join(t for t, *_ in words)
    if any(kw in text for kw in _HEX_KW):
        return "hex"
    if any(kw in text for kw in _DRAFT_KW):
        return "draft"
    return None


class PickEventGate:
    """事件门：去重 + 冷却，避免同事件反复报。"""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def admit(self, event: str) -> bool:
        """事件通过则记时间戳并返回 True；冷却期内返回 False。"""
        now = time.monotonic()
        if now - self._last.get(event, 0.0) < EVENT_COOLDOWN:
            return False
        self._last[event] = now
        return True
