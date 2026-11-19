"""冻结打包（PyInstaller）路径重定向。

红线自查：零输入模拟、零进程读取、零网络。

问题背景：onefile 模式下运行时 bundle 解压在临时目录（sys._MEIPASS），
只读资源（templates/units/traits/...）从 bundle 读没问题；但**写路径**
（对局 SQLite、pending 模板）落在临时目录会被系统清理，数据丢失。

方案：launcher 最先调用 patch_data_paths()——
- 读路径不变（loader 的 parents[2] 在 frozen 下自动指向 _MEIPASS）
- 写路径重定向到 exe 同级的 writable_data/ 目录
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def exe_dir() -> Path:
    """exe（或源码运行时项目根）所在目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]  # tft_copilot/paths.py -> 项目根


def writable_data_dir() -> Path:
    """可写数据根：源码运行=项目 data/；frozen=exe 旁 writable_data/。"""
    if is_frozen():
        d = exe_dir() / "writable_data"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return exe_dir() / "data"


def patch_data_paths() -> Path:
    """重定向写路径（幂等，源码运行为 no-op）。

    返回可写数据根目录。
    """
    wroot = writable_data_dir()
    if not is_frozen():
        return wroot

    # 1) 对局库默认路径（replay_cli 的 data/db/matches_v18.6.db）
    import tft_copilot.replay_cli as replay_cli

    replay_cli.DEFAULT_DB = str(wroot / "db" / "matches_v18.6.db")
    (wroot / "db").mkdir(parents=True, exist_ok=True)

    # 2) pending 模板目录（units_spotter 抓不到的截图归档）
    import tft_copilot.perception.units_spotter as spotter

    spotter.PENDING_DIR = wroot / "pending_templates"
    spotter.PENDING_DIR.mkdir(parents=True, exist_ok=True)
    return wroot
