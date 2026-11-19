"""M5 equips 数值库 CLI 子命令：统计 + 校验."""

from __future__ import annotations

import argparse
from collections import Counter

from tft_copilot.knowledge.equips_loader import DEFAULT_PATH, load_equips


def run(args: argparse.Namespace) -> int:
    try:
        book = load_equips(args.file)
    except Exception as err:  # noqa: BLE001 - CLI 汇总报错
        print(f"校验失败：{err}")
        return 1
    print(f"=== tft-copilot equips-check（源：{book.version_id} / patch {book.patch}）===")
    print(f"装备总数：{len(book)}")
    dist = Counter(e.type for e in book)
    for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    synth_n = sum(1 for e in book if e.synth)
    print(f"含合成路径：{synth_n} 件")
    grade_sum = sum(e.grade for e in book if e.type == "成型装备")
    print(f"成装 grade 合计：{grade_sum:.1f}（锚点 1.0 x 39）")
    print("校验通过 ✓")
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("equips-check", help="equips 装备库统计与校验（M5）")
    p.add_argument("--file", default=str(DEFAULT_PATH), help="装备库 JSON 路径")
    p.set_defaults(func=run)
