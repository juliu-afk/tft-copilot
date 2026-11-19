"""双击启动器：数字菜单（exe / python 交互入口）.

红线自查：零输入模拟、零进程读取、零网络（菜单选择是本程序自身输入）。

用法：
    双击 tft-copilot.exe                 # PyInstaller 打包后
    python -m tft_copilot.launcher       # 源码交互运行

菜单：
    [1] 实时副官（开游戏用这个）
    [2] 卡组推荐（进对局前）
    [3] 对局统计（打完复盘）
    [0] 退出
"""

from __future__ import annotations

import time

from tft_copilot.paths import patch_data_paths


def run_recommend() -> int:
    """交互式卡组推荐（复用 M4 DeckRecommender）。"""
    import argparse

    from tft_copilot.deck_check import cmd_recommend

    prefs = {"1": "balanced", "2": "economy", "3": "aggressive", "4": "gate"}
    print()
    print("偏好: [1]均衡 [2]经济 [3]激进 [4]守门")
    try:
        c = input("回车=均衡: ").strip()
    except (EOFError, KeyboardInterrupt):
        return 1
    pref = prefs.get(c, "balanced")
    try:
        task = input("本局任务（可空，如 连胜）: ").strip() or None
    except (EOFError, KeyboardInterrupt):
        task = None
    args = argparse.Namespace(pref=pref, task=task)
    return cmd_recommend(args)


def run_stats() -> int:
    """对局统计（复用 replay_cli.cmd_stats）。"""
    import argparse

    from tft_copilot.replay_cli import cmd_stats

    args = argparse.Namespace(db=None, match=None)
    return cmd_stats(args)


def menu_loop() -> int:
    """主菜单循环；返回进程退出码。"""
    patch_data_paths()
    while True:
        print()
        print("=" * 46)
        print("  金铲铲大橘大利 · 跑刀副官")
        print("=" * 46)
        print("  [1] 实时副官（开游戏时用，Ctrl+C 退出）")
        print("  [2] 卡组推荐（进对局前看选卡路线）")
        print("  [3] 对局统计（打完复盘）")
        print("  [0] 退出")
        print("-" * 46)
        try:
            choice = input("请选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            return 0
        t0 = time.perf_counter()
        if choice == "0":
            print("再见")
            return 0
        if choice == "1":
            from tft_copilot.live import start_live_command

            start_live_command()
            print(f"（副官会话用时 {(time.perf_counter() - t0):.0f}s）")
            continue
        if choice == "2":
            run_recommend()
            continue
        if choice == "3":
            run_stats()
            continue
        print("无效选择，请输入 0-3")


if __name__ == "__main__":
    raise SystemExit(menu_loop())
