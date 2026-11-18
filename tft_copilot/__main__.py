"""TFT Copilot 主包入口。

三条红线（凌驾一切设计决策）：
1. 零输入模拟 —— 不模拟任何鼠标键盘操作
2. 零进程读取 —— 不读游戏内存/句柄/网络包
3. 零联网外传 —— 运行时零网络请求，数据不出本地 SQLite
"""

from __future__ import annotations

import argparse
import sys

from tft_copilot.decision_check import add_subparser as add_decision_test
from tft_copilot.deck_check import add_subparser as add_deck_check
from tft_copilot.perception_check import add_subparser as add_perception_test
from tft_copilot.replay_cli import add_subparser as add_replay_cli
from tft_copilot.rules_check import add_subparser as add_rules_check
from tft_copilot.units_check import add_subparser as add_units_check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tft-copilot", description="金铲铲大橘大利本地只读副官")
    sub = parser.add_subparsers(dest="command")

    add_rules_check(sub)
    add_units_check(sub)
    add_perception_test(sub)
    add_decision_test(sub)
    add_replay_cli(sub)
    add_deck_check(sub)

    parsed = parser.parse_args(argv)
    if getattr(parsed, "func", None) is None:
        parser.print_help()
        return 0 if parsed.command is None else 1

    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main())
