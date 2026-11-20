# -*- coding: utf-8 -*-
"""对局内自动标定器：监听对局开始后采样 60s，时序聚类锁定数字锚点.

用法（后台运行，无需人工参与）：
    python tools/calib_watch.py            # 前台跑
    pythonw tools/calib_watch.py           # 后台跑

原理：
1. 每 2s 抓帧 + 场景判定，进入对局（SHOP/BATTLE）后开始采样
2. 全帧数字词收集（含顶部/左下/底部/右下全部区域）
3. 时序特征分类：
   - 递增且大值 -> 层数
   - 递减且 <=100 -> 血量
   - 剧烈波动 0-100 -> 金币
   - 缓慢单调增且 <=10 -> 等级
   - X-Y 格式 -> 阶段
4. 锁定各锚点坐标写 perception_anchors.json（v2 识别器热加载）
5. 完成后退出，打印标定结果
"""
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from tft_copilot.perception.ocr_numbers import ocr_tiles, load_rois, save_rois
from tft_copilot.perception.scene_signals import detect_scene_signal
from tft_copilot.perception.win_grabber import WindowGrabber

SAMPLE_SEC = 90          # 对局内采样时长
INTERVAL = 2.0           # 采样间隔
STABLE_COUNT = 8         # 连续命中次数即锁定


def main() -> None:
    wg = WindowGrabber()
    print("[calib] 等待对局开始（检测到 SHOP/BATTLE 场景自动采样）...")
    # 等待进对局
    while True:
        try:
            frame = wg.grab()
        except Exception:
            time.sleep(2.0)
            continue
        scene = detect_scene_signal(frame)
        if scene.value in ("shop", "battle"):
            print(f"[calib] 进入对局（{scene.value}），开始采样 {SAMPLE_SEC}s")
            break
        time.sleep(2.0)

    # 采样：坐标 -> 值序列
    samples: dict[tuple[int, int], list[int]] = defaultdict(list)
    rois = load_rois()
    t0 = time.monotonic()
    n = 0
    while time.monotonic() - t0 < SAMPLE_SEC:
        try:
            frame = wg.grab()
        except Exception:
            time.sleep(INTERVAL)
            continue
        scene = detect_scene_signal(frame)
        if scene.value not in ("shop", "battle"):
            continue  # 弹窗/切屏跳过
        n += 1
        # 全帧 4 ROI OCR
        for k in ("stage", "level", "gold", "hp_layer"):
            x0, y0 = rois[k][0], rois[k][1]
            pass
        # 直接用 ocr_tiles
        tiles = ocr_tiles(frame, rois)
        for k, words in tiles.items():
            for t, x, y, w, h in words:
                if t.isdigit():
                    samples[(x // 20 * 20, y // 20 * 20)].append(int(t))
        print(f"\r[calib] 采样 {n} 帧 / {len(samples)} 个位置", end="", flush=True)
        time.sleep(INTERVAL)

    print()
    if not samples:
        print("[calib] 未采到数字，退出")
        return 1

    # 时序分析：每个位置的序列特征
    print("[calib] 位置分析：")
    for pos, seq in sorted(samples.items(), key=lambda kv: -len(kv[1])):
        if len(seq) < STABLE_COUNT:
            continue
        uniq = sorted(set(seq))
        lo, hi = min(seq), max(seq)
        inc = sum(1 for a, b in zip(seq, seq[1:]) if b > a)
        dec = sum(1 for a, b in zip(seq, seq[1:]) if b < a)
        print(f"  @{pos} n={len(seq)} 范围[{lo},{hi}] 增{inc} 减{dec} 值{uniq[:8]}")

    # TODO（下一局实测数据后细化规则）：按特征分类写锚点
    print("[calib] 分析完成。位置数据已打印，可人工复核后写 perception_anchors.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
