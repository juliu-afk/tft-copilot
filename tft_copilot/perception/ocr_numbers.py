"""WinOCR 数字识别器 v2：多区域扫描 + 语义校验（M6 真机层重写）.

v1 教训（2026-11-20 实测翻车）：
- 只扫右栏面板 -> 金币(底部中间)/等级(左下)/阶段(顶部)根本不在扫描区
- 右栏道具文案数字（"获得2个微型英雄1复制器"）被误读为金币/等级
- 单帧标定的锚点被界面动态文案污染

v2 方案：
- 4 个语义 ROI 分区扫描（顶部阶段/左下等级/底部金币/右下层+血）
- 拼 tile 一次 OCR 调用（控制子进程开销）
- 语义校验：阶段 X-Y 格式 / 等级 1-10 / 金币 0-200 / 血 0-100
- 锚点坐标支持 JSON 热覆盖（data/perception_anchors.json）

红线自查：只读屏幕像素，无输入模拟。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np


def _ps1_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "tools" / "ocr_probe.ps1"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / "tools" / "ocr_probe.ps1"


_OCR_PS = _ps1_path()
_SCALE = 3

# 默认 ROI（1920x1080 标准帧）：可被 data/perception_anchors.json 覆盖
_DEFAULT_ROIS = {
    "stage": (640, 0, 640, 70),      # 顶部中央：X-Y 阶段文本
    "level": (330, 985, 200, 65),    # 左下：等级数字（1-10）
    "gold": (700, 920, 500, 80),     # 底部中间：金币（0-200）
    "hp_layer": (1690, 885, 230, 60),  # 右下：层数+血量
}
_ROI_ORDER = ("stage", "level", "gold", "hp_layer")
_TILE_GAP = 12  # tile 间空白像素（原图坐标系）


def _anchors_path() -> Path:
    """锚点热覆盖文件位置（frozen 走 writable_data）。"""
    try:
        from tft_copilot.paths import writable_data_root

        root = writable_data_root()
    except Exception:
        root = Path(__file__).resolve().parents[2] / "data"
    p = root / "perception_anchors.json"
    return p


def load_rois() -> dict[str, tuple[int, int, int, int]]:
    """读锚点配置：JSON 热覆盖 > 默认值。"""
    rois = dict(_DEFAULT_ROIS)
    p = _anchors_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k in _ROI_ORDER:
                if k in data:
                    rois[k] = tuple(data[k])  # type: ignore[assignment]
    except Exception:
        pass
    return rois  # type: ignore[return-value]


def save_rois(rois: dict) -> None:
    """锚点写盘（自动标定器用）。"""
    p = _anchors_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rois, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_ocr_ps(img_path: Path) -> list[tuple[str, int, int, int, int]]:
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


def ocr_tiles(frame: np.ndarray, rois: dict) -> dict[str, list[tuple[str, int, int, int, int]]]:
    """4 ROI 拼竖条一次 OCR，返回各 ROI 内的词（原图坐标）。"""
    tiles = []
    tops = []
    for k in _ROI_ORDER:
        x, y, w, h = rois[k]
        tiles.append(frame[y:y + h, x:x + w])
        tops.append(y)
    th = [t.shape[0] for t in tiles]
    gap = np.full((_TILE_GAP, tiles[0].shape[1], 3), 0, dtype=np.uint8)
    strips = []
    offsets = []
    cur = 0
    for t, h in zip(tiles, th):
        strips.append(t)
        offsets.append(cur)
        cur += h + _TILE_GAP
    # 等宽拼接（宽度取最大，不足补黑）
    wmax = max(t.shape[1] for t in strips)
    canvas_parts = []
    for t in strips:
        if t.shape[1] < wmax:
            pad = np.zeros((t.shape[0], wmax - t.shape[1], 3), dtype=np.uint8)
            t = np.hstack([t, pad])
        canvas_parts.append(t)
        canvas_parts.append(gap)
    canvas = np.vstack(canvas_parts[:-1])
    big = cv2.resize(canvas, None, fx=_SCALE, fy=_SCALE, interpolation=cv2.INTER_CUBIC)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "ocr.png"
        cv2.imwrite(str(tmp), big)
        words = _run_ocr_ps(tmp)
    out: dict[str, list] = {k: [] for k in _ROI_ORDER}
    for t, x, y, w, h in words:
        # y 反算到 canvas 原图坐标，再映射回 ROI
        oy = y // _SCALE
        for i, k in enumerate(_ROI_ORDER):
            lo, hi = offsets[i], offsets[i] + th[i]
            if lo <= oy < hi:
                rx, ry = rois[k][0] + x // _SCALE, rois[k][1] + (oy - lo)
                out[k].append((t, rx, ry, w // _SCALE, h // _SCALE))
                break
    return out


_STAGE_RE = re.compile(r"^(\d{1,2})[-.](\d{1,2})$")


def read_numbers_ocr(frame: np.ndarray) -> dict[str, int | None]:
    """读 5 项：stage_major/stage_minor/layer/gold/hp/level。

    语义校验：
    - stage: X-Y 格式，X 1-10, Y 1-7（大橘大利阶段-小节）
    - level: 1-10
    - gold: 0-200
    - hp: 0-100（右下靠右数字）
    - layer: 0-1500（右下靠左数字，跑刀累计层数）
    """
    rois = load_rois()
    tiles = ocr_tiles(frame, rois)
    out: dict[str, int | None] = {
        "stage_major": None, "stage_minor": None,
        "layer": None, "gold": None, "hp": None, "level": None,
    }
    # 1) stage：X-Y 文本
    for t, *_ in tiles["stage"]:
        m = _STAGE_RE.match(t.strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= 10 and 1 <= b <= 7:
                out["stage_major"], out["stage_minor"] = a, b
                break
    # 2) level：1-10 的数字
    cands = []
    for t, x, y, w, h in tiles["level"]:
        if t.isdigit():
            v = int(t)
            if 1 <= v <= 10:
                cands.append(v)
    if cands:
        out["level"] = max(cands)
    # 3) gold：0-200（底部中间区数字，排除刷新费用 2）
    golds = []
    for t, x, y, w, h in tiles["gold"]:
        if t.isdigit():
            v = int(t)
            if 0 <= v <= 200:
                golds.append((v, x))
    if golds:
        # 取 x 最小者：金币主数字在刷新按钮左侧，刷新费用 2D 在右
        golds.sort(key=lambda p: p[1])
        out["gold"] = golds[0][0]
    # 4) hp/layer：右下两数字，靠左=层，靠右=血
    nums = sorted(
        [(t, x, y, w, h) for t, x, y, w, h in tiles["hp_layer"] if t.isdigit()],
        key=lambda p: p[1],
    )
    valid = []
    for t, x, y, w, h in nums:
        v = int(t)
        if 0 <= v <= 1500:
            valid.append((v, x, w, h))
    if len(valid) >= 2:
        # 左侧（层数可大）+ 右侧（血 0-100）
        left, right = valid[0], valid[-1]
        out["layer"] = left[0]
        out["hp"] = right[0] if right[0] <= 100 else None
    elif len(valid) == 1:
        # 只识别到一个：靠右且 <=100 视为血量（大厅收藏角标 x>1890 排除）
        v, x, w, h = valid[0]
        if x > 1890 and v == 1:
            pass  # 大厅收藏按钮角标
        elif v <= 100 and x >= 1750:
            out["hp"] = v
        elif v > 100 or x < 1750:
            out["layer"] = v
    return out
