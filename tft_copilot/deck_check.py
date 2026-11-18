"""deck_check：卡组参谋 CLI（M4）。

子命令：
  deck-test                    冒烟：加载 201 卡 + 58 羁绊 + 四偏好推荐 + 校验清单输出
  recommend [--pref P] [--task T]  单次推荐 Top5
"""

from __future__ import annotations

import argparse
import time

from tft_copilot.deck.combo_scorer import ComboScorer, resolve_task_tags
from tft_copilot.deck.recommender import PREFERENCES, DeckRecommender
from tft_copilot.knowledge.cards_loader import load_cards
from tft_copilot.knowledge.traits_loader import load_traits


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("deck-test", help="卡组参谋冒烟（数据校验+四偏好推荐）")
    p.add_argument("--cards", default=None, help="cards JSON 路径（默认版本化路径）")
    p.add_argument("--traits", default=None, help="traits JSON 路径")
    p.set_defaults(func=cmd_deck_test)

    p2 = sub.add_parser("recommend", help="卡组推荐 Top5")
    p2.add_argument("--pref", default="balanced", choices=PREFERENCES, help="偏好")
    p2.add_argument("--task", default=None, help="本局任务名（可选，如 连胜）")
    p2.set_defaults(func=cmd_recommend)


def cmd_deck_test(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    print("== M4 卡组参谋冒烟 ==")
    book = load_cards(args.cards)
    print(f"[1] 时间卡片库: {book.stats()}")
    traits = load_traits(args.traits)
    n_bp = sum(1 for t in traits if t.num_list)
    print(f"[2] 羁绊断点表: {len(traits)} 羁绊 / {n_bp} 条带断点")

    sc = ComboScorer(book)
    tags = resolve_task_tags(None)
    singles = sc.single_scores(tags)
    n_missing = sum(1 for c in book if "desc_missing" in c.quality_flags)
    print(f"[3] 单卡预打分完成: {len(singles)} 卡（待人工校验描述 {n_missing} 张）")

    r = DeckRecommender(book)
    for pref in PREFERENCES:
        res = r.recommend(pref)
        top1 = res.combos[0]
        names = " + ".join(c.name for c in top1.cards)
        print(f"[4:{pref}] {res.elapsed_s:.2f}s 池{res.pool_size} 候选{res.candidates} Top1 {names}")

    elapsed = time.perf_counter() - t0
    print(f"== 冒烟通过 总耗时 {elapsed:.2f}s ==")
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    book = load_cards()
    r = DeckRecommender(book)
    res = r.recommend(args.pref, task_name=args.task)
    print(r.describe(res))
    return 0
