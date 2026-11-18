"""M1-2 units 数值库 CLI 子命令：统计 + 校验."""

from __future__ import annotations

import argparse
from collections import Counter

from tft_copilot.knowledge.units_loader import DATA_DIR, UnitsBook


def run(args: argparse.Namespace) -> int:
    files = sorted(DATA_DIR.glob("units_*.json"))
    if not files:
        print("未找到 data/units/units_*.json，先运行 tools/fetch_units.py")
        return 1
    book = UnitsBook.from_file(str(files[-1]))
    print(f"=== tft-copilot units-check（源：{book.meta['source']} / {book.meta['mode_code']}）===")
    print(f"条目总数：{len(book)}（重复对 {len(book.redundant_ids)}，去重后 {len(book.dedup_view())}）")
    cost_stat = Counter(u.cost for u in book)
    print("费用分布：", " ".join(f"{c}费={n}" for c, n in sorted(cost_stat.items())))
    trait_reg = book.trait_registry()
    print(f"羁绊种类：{len(trait_reg)} 个")
    top_traits = sorted(trait_reg.items(), key=lambda kv: -kv[1])[:8]
    print("规模前8羁绊：", "、".join(f"{t}({n})" for t, n in top_traits))
    flags = Counter(f for u in book for f in (u.quality_flags or ()))
    print("quality_flags：", dict(flags) if flags else "无")
    print("校验通过 ✓")
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("units-check", help="units 数值库统计与校验")
    p.set_defaults(func=run)
