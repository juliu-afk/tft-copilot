"""复盘回放 CLI：replay / stats / export（工程方案 9.3，A6）。

红线自查：零网络、零输入模拟、零进程读取。
"""

from __future__ import annotations

import csv
from pathlib import Path

from tft_copilot.store.db import MatchStore

# 四象限统计的样本量警示阈值（PRD 7.1）
QUADRANT_MIN_SAMPLES = 20
# 高置信判定阈值：winrate >=0.65 或 <=0.35
Q_HIGH_WR = 0.65
Q_LOW_WR = 0.35


def _open_store(args) -> MatchStore:
    db = Path(args.db) if getattr(args, "db", None) else Path("data/db/matches_v18.6.db")
    if not db.exists():
        raise SystemExit(f"对局库不存在: {db}（先跑 decision-test 或实局采集）")
    return MatchStore(db, _sniff_version(db))


def _sniff_version(db: Path) -> str:
    """读库内既有版本（只读打开，避免版本拒写误伤 replay）。"""
    import sqlite3

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT DISTINCT version FROM matches LIMIT 1").fetchone()
        if row:
            return row[0]
        row = conn.execute("SELECT DISTINCT version FROM rounds LIMIT 1").fetchone()
        return row[0] if row else "18.6"
    finally:
        conn.close()


# ---------- replay ----------

def replay_summary(rounds: list[dict], tail_only: bool = False) -> None:
    """打印回合明细（快照 + 预测 vs 实际）。"""
    if tail_only:
        print("-- 最后 5 回合摘要 --")
    for r in rounds:
        wr = r.get("predicted_winrate")
        wr_s = f"{wr * 100:.0f}%" if wr is not None else "?"
        units = ", ".join(
            f"{u['unit_id']}({u['star'] or 1}星)" for u in (r.get("my_units") or [])[:5]
        )
        if len(r.get("my_units") or []) > 5:
            units += " ..."
        print(
            f"R{r['round_no']:>3} 层{r.get('layers') or '?':>4} "
            f"血{r.get('hp') if r.get('hp') is not None else '?':>3} "
            f"战力{r.get('power_score') if r.get('power_score') is not None else '?':>5} "
            f"对位[{r.get('opp_player') or '-'}] 预测{wr_s:>4} 实际{r.get('actual_result') or '-'}"
            f" | {units}"
        )
        for a in r.get("advices") or []:
            print(f"      [{a['level']}] {a['text']}")


def cmd_replay(args) -> int:
    store = _open_store(args)
    m = store.get_match(args.match)
    if not m:
        print(f"match {args.match} 不存在")
        return 1
    print(
        f"== 对局 {m['id']}（{m['start_time'][:19]} -> {(m['end_time'] or '进行中')[:19]}）=="
        f" 版本 {m['version']} | 终局 第{m['final_place']}名 {m['final_layers']}层 {m['win_loss'] or ''}"
    )
    rounds = store.get_rounds(args.match)
    if args.round:
        rounds = [r for r in rounds if r["round_no"] == args.round]
        if not rounds:
            print(f"回合 {args.round} 不存在")
            return 1
    replay_summary(rounds)
    store.close()
    return 0


# ---------- stats ----------

def quadrant_summary(preds: list[tuple]) -> None:
    """四象限统计：高置信x对 / 高置信x错 / 低置信x对 / 低置信x错（工程方案 5.3）。"""
    q = {"hi_right": 0, "hi_wrong": 0, "lo_right": 0, "lo_wrong": 0}
    n_done = 0
    for wr, conf, actual in preds:
        if wr is None or actual is None:
            continue
        n_done += 1
        high_conf = conf == "high" or wr >= Q_HIGH_WR or wr <= Q_LOW_WR
        predicted_win = wr >= 0.5
        actual_win = actual in ("W",)  # I(故意输) 不计入判定
        if actual == "I":
            continue
        right = predicted_win == actual_win
        if high_conf:
            q["hi_right" if right else "hi_wrong"] += 1
        else:
            q["lo_right" if right else "lo_wrong"] += 1
    total = q["hi_right"] + q["hi_wrong"]
    rate = q["hi_wrong"] / total * 100 if total else 0.0
    print("-- 四象限统计 --")
    print(
        f"高置信x对 {q['hi_right']} | 高置信x错 {q['hi_wrong']}"
        f" | 低置信x对 {q['lo_right']} | 低置信x错 {q['lo_wrong']}"
    )
    if total:
        print(f"高置信判错率 {rate:.1f}%（真实判错率口径，M5 验收 <=15%）")
    if n_done < QUADRANT_MIN_SAMPLES:
        print(f"样本 {n_done} < {QUADRANT_MIN_SAMPLES}：样本不足，仅供观察")


def cmd_stats(args) -> int:
    store = _open_store(args)
    matches = store.list_matches()
    print(f"== 对局库（{len(matches)} 局）==")
    for m in matches:
        status = "闭合" if m["end_time"] else "进行中"
        print(
            f"  #{m['id']} {m['start_time'][:19]} v{m['version']} {status}"
            f" 第{m['final_place']}名 {m['final_layers']}层 {m['win_loss'] or ''}"
        )
    preds = store.all_predictions(getattr(args, "match", None))
    quadrant_summary(preds)
    store.close()
    return 0


# ---------- export ----------

def cmd_export(args) -> int:
    store = _open_store(args)
    out = Path(args.csv)
    out.mkdir(parents=True, exist_ok=True)
    # matches.csv
    matches = store.list_matches()
    with (out / "matches.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(matches[0].keys()) if matches else ["id"])
        w.writeheader()
        w.writerows(matches)
    # rounds.csv
    with (out / "rounds.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "match_id", "round_no", "version", "scene", "quality", "layers", "hp",
                "gold", "level", "my_units", "power_score", "opp_player",
                "predicted_winrate", "prediction_confidence", "actual_result", "advices",
            ]
        )
        for m in matches:
            for r in store.get_rounds(m["id"]):
                w.writerow(
                    [
                        m["id"], r["round_no"], store.db_version, r["scene"], r["quality"],
                        r["layers"], r["hp"], r["gold"], r["level"],
                        str(r["my_units"]), r["power_score"], r["opp_player"],
                        r["predicted_winrate"], r["prediction_confidence"],
                        r["actual_result"], str(r["advices"]),
                    ]
                )
    n_r = sum(store.get_rounds(m["id"]).__len__() for m in matches)
    print(f"导出完成: {out / 'matches.csv'}（{len(matches)} 局）")
    print(f"导出完成: {out / 'rounds.csv'}（{n_r} 回合）")
    store.close()
    return 0


def add_subparser(sub) -> None:
    for name, fn, help_ in [
        ("replay", cmd_replay, "逐回合回放对局"),
        ("stats", cmd_stats, "对局统计（含四象限）"),
        ("export", cmd_export, "导出 CSV"),
    ]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--db", default=None, help="SQLite 路径（默认 data/db/matches_v18.6.db）")
        if name == "replay":
            p.add_argument("--match", type=int, required=True, help="对局 id")
            p.add_argument("--round", type=int, default=None, help="跳到指定回合")
        if name == "stats":
            p.add_argument("--match", type=int, default=None, help="限定单局")
        if name == "export":
            p.add_argument("--csv", required=True, help="导出目录")
        p.set_defaults(func=fn)
