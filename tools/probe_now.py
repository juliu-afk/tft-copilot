# -*- coding: utf-8 -*-
"""实测当前游戏窗口状态：抓帧+场景识别+OCR 读数。"""
import sys

sys.path.insert(0, r"D:\tft-copilot")

import numpy as np

from tft_copilot.perception.win_grabber import WindowGrabber, find_game_window
from tft_copilot.perception.scene_signals import detect_scene_signal, scene_signal_scores


def main() -> None:
    hwnd = find_game_window()
    print("游戏窗口:", hwnd if hwnd else "未找到（游戏没开或窗口标题不匹配）")
    if hwnd is None:
        return
    try:
        frame = WindowGrabber().grab()
        print("抓帧成功:", frame.shape)
    except Exception as exc:
        print("抓帧失败:", exc)
        return
    scores = scene_signal_scores(frame)
    print("结构信号:", {k: round(v, 1) for k, v in scores.items()})
    from tft_copilot.perception.ocr_numbers import read_numbers_ocr
    nums = read_numbers_ocr(frame)
    print("read_numbers_ocr:", nums)
    from tft_copilot.perception.ocr_numbers import ocr_words
    words = ocr_words(frame)
    print(f"OCR 全部词 {len(words)} 个:")
    for t, x, y, w, h in words:
        mark = " <NUM>" if t.isdigit() else ""
        print(f"  '{t}' @({x},{y}) {w}x{h}{mark}")


if __name__ == "__main__":
    main()
