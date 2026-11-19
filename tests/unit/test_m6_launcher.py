"""launcher 菜单交互测试（input 打桩）。"""
from __future__ import annotations

import builtins

from tft_copilot.launcher import menu_loop


def test_menu_exit_immediately(capsys):
    builtins.input = lambda *a: "0"
    try:
        rc = menu_loop()
    finally:
        del builtins.input
    assert rc == 0
    assert "实时副官" in capsys.readouterr().out


def test_menu_invalid_then_exit(capsys):
    answers = iter(["9", "0"])
    builtins.input = lambda *a: next(answers)
    try:
        rc = menu_loop()
    finally:
        del builtins.input
    assert rc == 0
    out = capsys.readouterr().out
    assert "无效选择" in out


def test_menu_stats_calls_cli(capsys):
    """选3=对局统计（cmd_stats 无库时应正常返回而非崩溃）。"""
    answers = iter(["3", "0"])
    builtins.input = lambda *a: next(answers)
    try:
        rc = menu_loop()
    finally:
        del builtins.input
    assert rc == 0
