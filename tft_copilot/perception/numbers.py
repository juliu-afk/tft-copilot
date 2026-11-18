"""NumberReader：ROI -> 整数（悲观分割 + 逐字符模板匹配）.

budget: 60ms/frame（4 个数字 ROI 合计）
方案 D4：对 ROI 内每个数字模板做全图匹配，收集所有得分 >= 阈值的
字符框（悲观：宁多勿漏），按 x 排序去重叠后拼接数字串。
"""

from __future__ import annotations

import cv2
import numpy as np

from tft_copilot.perception.templates import TemplateBank

SCORE_TH = 0.58  # 单字符阈值（合成帧 sigma=6 噪声标定）
IOU_MERGE = 0.3  # 字符框重叠合并阈值


def _match_char(sub: np.ndarray, tpl: np.ndarray) -> tuple[float, tuple[int, int, int, int]]:
    """单字符匹配：返回 (得分, 最佳位置框)。"""
    res = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    h, w = tpl.shape[:2]
    return float(mx), (loc[0], loc[1], w, h)


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ix = max(0, min(ax1 + aw, bx1 + bw) - max(ax1, bx1))
    iy = max(0, min(ay1 + ah, by1 + bh) - max(ay1, by1))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def read_number(frame: np.ndarray, roi: tuple[int, int, int, int], bank: TemplateBank) -> int | None:
    """识别 ROI 内整数。失败返回 None（调用方降级）。

    流程：ROI 裁剪 -> 灰度 -> 对 0-9 全模板匹配（彩色池由 bank 提供，
    匹配在灰度域进行降低光照敏感）-> 收集高分框 -> x 排序去重 -> 拼串。
    """
    x, y, w, h = roi
    sub = frame[y : y + h, x : x + w]
    if sub.size == 0:
        return None
    gray_sub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)

    # 每个数字取各颜色池最高分（灰度域颜色差异弱化，颜色池主要供真机彩色匹配）
    digit_boxes: list[tuple[int, float, tuple[int, int, int, int]]] = []
    for d in range(10):
        best_score = -1.0
        best_box = None
        for color_key, tpl in bank.digits.items():
            if not color_key.startswith(f"digit_{d}_"):
                continue
            gtpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            th, tw = gtpl.shape[:2]
            if th > sub.shape[0] or tw > sub.shape[1]:
                continue
            score, box = _match_char(gray_sub, gtpl)
            if score > best_score:
                best_score = score
                best_box = box
        if best_score >= SCORE_TH and best_box is not None:
            digit_boxes.append((d, best_score, best_box))

    if not digit_boxes:
        return None

    # 按得分降序保留，重叠框去掉低分者（同位置多字符竞争）
    digit_boxes.sort(key=lambda t: -t[1])
    kept: list[tuple[int, float, tuple[int, int, int, int]]] = []
    for d, sc, box in digit_boxes:
        if all(_iou(box, kb[2]) < IOU_MERGE for kb in kept):
            kept.append((d, sc, box))

    kept.sort(key=lambda t: t[2][0])  # x 排序
    text = "".join(str(d) for d, _, _ in kept)
    try:
        return int(text)
    except ValueError:
        return None
