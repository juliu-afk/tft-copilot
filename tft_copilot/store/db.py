"""对局库：SQLite matches/rounds 两表 + WAL（工程方案 9.1）。

版本化铁律：version 列必填，库文件版本与知识库 patch 不一致拒写。
红线自查：零网络、零输入模拟、零进程读取（SQLite 本地文件）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    version TEXT NOT NULL,
    final_layers INTEGER,
    final_place INTEGER,
    win_loss TEXT
);
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    round_no INTEGER NOT NULL,
    version TEXT NOT NULL,
    scene TEXT,
    quality REAL,
    layers INTEGER,
    hp INTEGER,
    gold INTEGER,
    level INTEGER,
    my_units TEXT,
    power_score REAL,
    opp_player TEXT,
    predicted_winrate REAL,
    prediction_confidence TEXT,
    actual_result TEXT,
    advices TEXT
);
CREATE INDEX IF NOT EXISTS idx_rounds_match ON rounds(match_id, round_no);
"""


class MatchStoreVersionError(Exception):
    """版本不匹配拒写（铁律：版本不匹配的数据拒绝入库）。"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class MatchStore:
    """对局库读写。所有写入带版本；读取供 replay/stats/export。"""

    def __init__(self, path: str | Path, version: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        # M5 迁移：rounds 加 pred_engine 列（幂等，旧库自动升级）
        try:
            self._conn.execute("ALTER TABLE rounds ADD COLUMN pred_engine TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在
        self._conn.commit()
        # 库级版本锚定：matches 表首个版本即库版本；不一致拒写
        row = self._conn.execute(
            "SELECT DISTINCT version FROM matches LIMIT 1"
        ).fetchone()
        if row is not None and row[0] != version:
            self._conn.close()
            raise MatchStoreVersionError(
                f"库版本 {row[0]} 与请求版本 {version} 不一致，拒绝入库（版本化铁律）"
            )
        self._version = version

    # ---------- 写 ----------

    def start_match(self) -> int:
        cur = self._conn.execute(
            "INSERT INTO matches(start_time, version) VALUES (?, ?)",
            (_now(), self._version),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def record_round(
        self,
        match_id: int,
        round_no: int,
        scene: str | None,
        quality: float | None,
        layers: int | None,
        hp: int | None,
        gold: int | None,
        level: int | None,
        my_units: list | None,
        power_score: float | None,
        opp_player: str | None,
        predicted_winrate: float | None,
        prediction_confidence: str | None,
        advices: list | None,
        pred_engine: str | None = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO rounds(match_id, round_no, version, scene, quality,
               layers, hp, gold, level, my_units, power_score,
               opp_player, predicted_winrate, prediction_confidence,
               actual_result, advices, pred_engine)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)""",
            (
                match_id,
                round_no,
                self._version,
                scene,
                quality,
                layers,
                hp,
                gold,
                level,
                json.dumps(
                    [
                        {
                            "unit_id": u.unit_id,
                            "cost": u.cost,
                            "star": u.star,
                            "score": u.score,
                        }
                        for u in (my_units or [])
                    ],
                    ensure_ascii=False,
                ),
                power_score,
                opp_player,
                predicted_winrate,
                prediction_confidence,
                json.dumps(
                    [{"level": a.level, "text": a.text, "source": a.source} for a in (advices or [])],
                    ensure_ascii=False,
                ),
                pred_engine,
            ),
        )
        self._conn.commit()

    def record_result(self, match_id: int, round_no: int, result: str) -> None:
        """补记回合胜负：W / L / I(故意输)。供四象限统计。"""
        if result not in ("W", "L", "I"):
            raise ValueError(f"result 非法: {result!r}（须 W/L/I）")
        self._conn.execute(
            """UPDATE rounds SET actual_result = ?
               WHERE match_id = ? AND round_no = ?
               AND actual_result IS NULL""",
            (result, match_id, round_no),
        )
        self._conn.commit()

    def close_match(
        self,
        match_id: int,
        final_place: int | None,
        final_layers: int | None,
        win_loss: str,
    ) -> None:
        """闭合对局：end_time + 终局数据 + W/L 序列。"""
        if not win_loss or any(c not in "WLI" for c in win_loss):
            raise ValueError(f"win_loss 序列非法: {win_loss!r}")
        self._conn.execute(
            """UPDATE matches SET end_time = ?, final_place = ?,
               final_layers = ?, win_loss = ? WHERE id = ?""",
            (_now(), final_place, final_layers, win_loss, match_id),
        )
        self._conn.commit()

    # ---------- 读 ----------

    def open_unclosed(self) -> list[int]:
        """断线续采：未闭合对局 id 列表（US-6b）。"""
        rows = self._conn.execute(
            "SELECT id FROM matches WHERE end_time IS NULL ORDER BY id"
        ).fetchall()
        return [r[0] for r in rows]

    def get_match(self, match_id: int) -> dict:
        row = self._conn.execute(
            """SELECT id, start_time, end_time, version, final_layers,
               final_place, win_loss FROM matches WHERE id = ?""",
            (match_id,),
        ).fetchone()
        cols = ["id", "start_time", "end_time", "version", "final_layers", "final_place", "win_loss"]
        return dict(zip(cols, row, strict=True)) if row else {}

    def get_rounds(self, match_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT round_no, scene, quality, layers, hp, gold, level,
               my_units, power_score, opp_player, predicted_winrate,
               prediction_confidence, actual_result, advices
               FROM rounds WHERE match_id = ? ORDER BY round_no""",
            (match_id,),
        ).fetchall()
        cols = [
            "round_no", "scene", "quality", "layers", "hp", "gold", "level",
            "my_units", "power_score", "opp_player", "predicted_winrate",
            "prediction_confidence", "actual_result", "advices",
        ]
        out = []
        for r in rows:
            d = dict(zip(cols, r, strict=True))
            d["my_units"] = json.loads(d["my_units"] or "[]")
            d["advices"] = json.loads(d["advices"] or "[]")
            out.append(d)
        return out

    def all_predictions(self, match_id: int | None = None) -> list[tuple]:
        """(predicted_winrate, confidence, actual_result, pred_engine) 四元组，四象限统计用。

        pred_engine: 'L1.5' | 'L0' | NULL（M3 旧数据无该列值，按 NULL 归 L0 口径展示）。
        """
        if match_id is None:
            rows = self._conn.execute(
                """SELECT predicted_winrate, prediction_confidence, actual_result, pred_engine
                   FROM rounds WHERE predicted_winrate IS NOT NULL"""
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT predicted_winrate, prediction_confidence, actual_result, pred_engine
                   FROM rounds WHERE predicted_winrate IS NOT NULL AND match_id = ?""",
                (match_id,),
            ).fetchall()
        return rows

    def list_matches(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT id, start_time, end_time, version, final_layers,
               final_place, win_loss FROM matches ORDER BY id"""
        ).fetchall()
        cols = ["id", "start_time", "end_time", "version", "final_layers", "final_place", "win_loss"]
        return [dict(zip(cols, r, strict=True)) for r in rows]

    @property
    def db_version(self) -> str:
        return self._version

    def close(self) -> None:
        self._conn.close()
