# -*- coding: utf-8 -*-
"""TFT Copilot 主包入口。

三条红线（凌驾一切设计决策）：
1. 零输入模拟 —— 不模拟任何鼠标键盘操作
2. 零进程读取 —— 不读游戏内存/句柄/网络包
3. 零联网外传 —— 运行时零网络请求，数据不出本地 SQLite
"""


def main() -> None:
    """CLI 入口（M1 里程碑后逐步实装）。"""
    print("TFT Copilot v0.1.0 —— 机器补记忆，人补导航")
    print("状态：脚手架阶段，见 docs/roadmap.md")


if __name__ == "__main__":
    main()
