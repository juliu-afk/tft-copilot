"""rules-check CLI 子命令：规则库统计与校验。"""

from __future__ import annotations

import argparse

from tft_copilot.knowledge import load_rules


def run(parsed: argparse.Namespace) -> int:
    try:
        bundle = load_rules(patch=parsed.patch)
    except Exception as exc:  # 校验失败即退出码 1
        print(f"[FAIL] 规则库加载失败: {exc}")
        return 1

    tasks = bundle.tasks
    by_cat: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for t in tasks.values():
        by_cat[t.category] = by_cat.get(t.category, 0) + 1
        by_tier[t.tier] = by_tier.get(t.tier, 0) + 1

    print(f"规则库 rules_{bundle.patch}.json 校验通过 ✓")
    print(f"任务总数: {len(tasks)}")
    print(f"奖励档数: {len(bundle.rewards)}（{bundle.rewards[0].layers}~{bundle.rewards[-1].layers} 层）")
    print(f"钥匙数量: {len(bundle.keys)}")
    print(f"路线数量: {len(bundle.routes)}")
    print("任务分类:", " ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
    print("任务评级:", " ".join(f"{k}={v}" for k, v in sorted(by_tier.items())))
    return 0


def add_subparser(sub: argparse.ArgumentParser) -> None:
    p = sub.add_parser("rules-check", help="规则库统计与三重校验")
    p.add_argument("--patch", default="18.6", help="游戏版本号（默认 18.6）")
    p.set_defaults(func=run)
