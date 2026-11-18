"""decision-test CLI：合成局端到端冒烟（技术方案 §10，A9）。

seeded RNG 造合成局：8 家 x N 回合，层数递增、血量递减、
随机抽卡，跑 DecisionEngine 全链路，最后 replay 摘要输出。
红线自查：零网络、零输入模拟、零进程读取。
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

from tft_copilot.decision.engine import DecisionEngine
from tft_copilot.decision.snapshot import BoardSnapshot, PlayerState, TaskState, UnitOnBoard
from tft_copilot.knowledge.rules_loader import load_rules
from tft_copilot.knowledge.units_loader import UnitsBook
from tft_copilot.overlay.hud import ConsoleHUD
from tft_copilot.store.db import MatchStore


def add_subparser(sub) -> None:
    p = sub.add_parser("decision-test", help="合成局决策链路端到端冒烟")
    p.add_argument("--db", default=None, help="SQLite 路径（默认临时库）")
    p.add_argument("--rounds", type=int, default=30, help="模拟回合数")
    p.add_argument("--seed", type=int, default=20261118, help="随机种子")
    p.set_defaults(func=run)


def run(args) -> int:
    rng = random.Random(args.seed)
    rules = load_rules()
    book = UnitsBook.from_file(Path("data/units/units_18.6.json"))

    db_path = args.db or str(Path(tempfile.gettempdir()) / "tft_decision_smoke.db")
    store = MatchStore(db_path, rules.patch)
    hud = ConsoleHUD(quiet=True)
    eng = DecisionEngine(rules, book, store=store, hud=hud)

    mid = eng.start_match()
    print(f"== 合成局冒烟（match={mid}, rounds={args.rounds}, seed={args.seed}）==")

    all_ids = [u.id for u in book]
    # 8 家初始阵容（随机 10 子）
    players: dict[str, PlayerState] = {}
    for i, name in enumerate(["me"] + [f"p{j}" for j in range(1, 8)]):
        n_units = rng.randint(6, 10)
        units = [
            UnitOnBoard(rng.choice(all_ids), 1, rng.choice([1, 1, 2]), 0.99)
            for _ in range(n_units)
        ]
        players[name] = PlayerState(name, units, 80 - i * 3, [80 - i * 3])

    task = TaskState("lose" if args.seed % 2 == 0 else "win", 3)
    layers = 0
    max_cost_ms = 0.0
    total_advices = 0

    for r in range(1, args.rounds + 1):
        # 层数单调递增（0-25/回合），血量缓慢下降
        layers = min(layers + rng.randint(0, 25), 1300)
        for ps in players.values():
            ps.hp = max(ps.hp - rng.randint(0, 4), 1) if ps.hp else 1
            ps.hp_history.append(ps.hp)
            if len(ps.hp_history) > 6:
                ps.hp_history.pop(0)
            # 每回合小概率换卡（阵容演进）
            if rng.random() < 0.3 and ps.units:
                idx = rng.randrange(len(ps.units))
                ps.units[idx] = UnitOnBoard(rng.choice(all_ids), 1, rng.choice([1, 2]), 0.99)
        snap = BoardSnapshot(
            round_no=r,
            scene=rng.choice(["shop", "battle", "planning"]),
            quality=0.95,
            my_units=players["me"].units,
            layers=layers,
            hp=players["me"].hp,
            gold=rng.randint(10, 80),
            level=min(7 + r // 10, 9),
        )
        next_opp = rng.choice([f"p{j}" for j in range(1, 8)])
        advices = eng.on_round(snap, players, next_opp=next_opp, task=task)
        total_advices += len(advices)
        max_cost_ms = max(max_cost_ms, eng.last_cost_ms)
        # 回合胜负：W/L 随机 + 对位高胜率偏 W
        result = "W" if rng.random() < 0.55 else "L"
        eng.record_result(r, result)

    eng.close_match(rng.randint(1, 8), layers, "WL" * (args.rounds // 2))

    print(f"回合数 {args.rounds} | 峰值单轮 {max_cost_ms:.1f}ms | 建议总数 {total_advices}")
    if max_cost_ms > 50:
        print(f"[FAIL] 单轮预算超限: {max_cost_ms:.1f}ms > 50ms")
        return 1

    # replay 摘要（最后 5 回合）
    from tft_copilot.replay_cli import replay_summary

    rounds = store.get_rounds(mid)
    replay_summary(rounds[-5:], tail_only=True)
    # 四象限一行
    from tft_copilot.replay_cli import quadrant_summary

    quadrant_summary(store.all_predictions(mid))
    store.close()
    print("== decision-test 冒烟通过 ==")
    return 0
