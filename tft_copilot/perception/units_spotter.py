"""UnitSpotter：ROI 区域 -> UnitBox 列表（两级金字塔匹配 + 星级角标）.

budget: 100ms/frame（小 ROI 单次；商店整条按 anchors 逐卡调用）
架构（实测标定）：
  L1 半分辨率单尺度粗筛（122 模板 -> top15 存活）
  L2 全分辨率多尺度精配（存活者 0.8/1.0/1.2）
阈值依据：合成帧真目标 >=0.99 / 假阳性 <=0.56（native-size 基准），
取分离带中点 0.80；真机标定后由 M6 校准。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from tft_copilot.perception.templates import TemplateBank

L1_KEEP = 15          # L1 存活数
L2_SCALES = (0.8, 1.0, 1.2)
MATCH_TH = 0.80       # 头像匹配阈值（合成帧分离带中点）
STAR_TH = 0.55        # 星角标阈值
PENDING_TH = 0.45     # 低分候选裁剪落盘阈值
PENDING_DIR = Path(__file__).resolve().parents[2] / "data" / "pending_templates"


@dataclass(frozen=True)
class UnitBox:
    unit_id: str
    name: str
    cost: int
    star: int | None
    bbox: tuple[int, int, int, int]  # ROI 内相对坐标
    score: float


class UnitSpotter:
    """识别 ROI 内弈子：两级金字塔 + 星角标。"""

    def __init__(self, bank: TemplateBank, pending_dir: Path | None = None) -> None:
        self._bank = bank
        self._pending_dir = pending_dir or PENDING_DIR
        # 灰度金字塔：L1 半分辨率 + L2 三尺度，加载期预计算
        self._l1: dict[str, np.ndarray] = {}
        self._l2: dict[str, list[tuple[float, np.ndarray]]] = {}
        for uid, img in bank.portraits.items():
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            self._l1[uid] = cv2.resize(g, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            self._l2[uid] = [
                (s, cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s != 1.0 else g)
                for s in L2_SCALES
            ]

    def spot(self, frame: np.ndarray, area: tuple[int, int, int, int]) -> list[UnitBox]:
        """识别一个 ROI 区域（area 为全帧坐标）。"""
        x, y, w, h = area
        sub = cv2.cvtColor(frame[y : y + h, x : x + w], cv2.COLOR_BGR2GRAY)
        if sub.size == 0:
            return []

        # L1 粗筛
        sub_half = cv2.resize(sub, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        l1_scores: dict[str, float] = {}
        for uid, tpl in self._l1.items():
            if tpl.shape[0] > sub_half.shape[0] or tpl.shape[1] > sub_half.shape[1]:
                continue
            res = cv2.matchTemplate(sub_half, tpl, cv2.TM_CCOEFF_NORMED)
            l1_scores[uid] = float(res.max())
        if not l1_scores:
            return []
        survivors = sorted(l1_scores.items(), key=lambda kv: -kv[1])[:L1_KEEP]

        # L2 精配（仅存活者）
        results: list[tuple[str, float, tuple[int, int, int, int]]] = []
        for uid, _ in survivors:
            best = (-1.0, None)
            for _, tpl in self._l2[uid]:
                if tpl.shape[0] > sub.shape[0] or tpl.shape[1] > sub.shape[1]:
                    continue
                res = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
                _, mx, _, loc = cv2.minMaxLoc(res)
                if mx > best[0]:
                    best = (float(mx), (loc[0], loc[1], tpl.shape[1], tpl.shape[0]))
            if best[1] is not None:
                results.append((uid, best[0], best[1]))

        # 同位置竞争（IOU>0.5 取高分）+ 星角标
        results.sort(key=lambda t: -t[1])
        boxes: list[UnitBox] = []
        taken: list[tuple[int, int, int, int]] = []
        for uid, score, bbox in results:
            if score < MATCH_TH:
                break
            if any(_iou(bbox, t) > 0.5 for t in taken):
                continue
            star = self._match_star(sub, bbox)
            name, cost = self._unit_info(uid)
            boxes.append(UnitBox(uid, name, cost, star, bbox, round(score, 3)))
            taken.append(bbox)

        # 低分候选落 pending：低于 PENDING_TH 的 top1 落盘
        if results and results[0][1] < PENDING_TH:
            self._dump_pending(sub, results[0][2], results[0][1])
        return boxes

    def _match_star(self, sub_gray: np.ndarray, bbox: tuple[int, int, int, int]) -> int | None:
        """在头像框右下角小区域匹配罗马数字角标。"""
        x, y, w, h = bbox
        sx, sy = x + w // 2, y + h // 2
        region = sub_gray[sy : sy + h // 2, sx : sx + w // 2]
        if region.size == 0:
            return None
        best_star, best_score = None, -1.0
        for key, tpl in self._bank.stars.items():
            gt = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            if gt.shape[0] > region.shape[0] or gt.shape[1] > region.shape[1]:
                continue
            res = cv2.matchTemplate(region, gt, cv2.TM_CCOEFF_NORMED)
            mx = float(res.max())
            if mx > best_score:
                best_score, best_star = mx, int(key.split("_")[1])
        return best_star if best_score >= STAR_TH else None

    def _dump_pending(self, sub_gray: np.ndarray, bbox: tuple[int, int, int, int], score: float) -> None:
        """低分候选裁剪落盘（文件名带坐标+分数+时间戳）。"""
        try:
            self._pending_dir.mkdir(parents=True, exist_ok=True)
            x, y, w, h = bbox
            crop = sub_gray[y : y + h, x : x + w]
            if crop.size == 0:
                return
            ts = time.strftime("%H%M%S")
            name = f"pending_{x}_{y}_{score:.2f}_{ts}.png"
            cv2.imwrite(str(self._pending_dir / name), crop)
        except OSError:
            pass  # pending 落盘失败不影响主流程

    def _unit_info(self, uid: str) -> tuple[str, int]:
        """unit_id -> (name, cost)。感知层零知识依赖，cost 由 ID 前缀轻量解析。"""
        cost = int(uid[:2]) - 10 if uid[:2].isdigit() else 0
        return uid, cost  # name 由决策层经 UnitsBook 补全


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0
