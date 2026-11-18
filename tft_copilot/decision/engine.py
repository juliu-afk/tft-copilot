"""决策编排引擎：四模块串联 + 去重 + HUD + 落库（技术方案 §9）。

budget: 单轮 <=50ms（A8，纯 dict/list 运算无 IO 循环）。
红线自查：零网络、零输入模拟、零进程读取。SQLite 为本地文件。
E7 处理：落库 OperationalError -> 内存模式降级（store 置 None，Toast 一次）。
"""

from __future__ import annotations

import time

from tft_copilot.decision.impact import evaluate as impact_evaluate
from tft_copilot.decision.layer_progress import MILESTONES, LayerProgress, build_rewards_map
from tft_copilot.decision.matchup import advice_for, predict
from tft_copilot.decision.power_score import PowerScorer
from tft_copilot.decision.snapshot import (
    BoardSnapshot,
    LayersGuard,
    PlayerState,
    TaskState,
    quality_gate,
)
from tft_copilot.knowledge.rules_loader import RulesBundle
from tft_copilot.knowledge.units_loader import UnitsBook
from tft_copilot.overlay.hud import ConsoleHUD, HUDBase, HUDState


class DecisionEngine:
    """四模块编排：质量门卫 -> 层数卫兵 -> 四模块 -> 去重 -> HUD -> 落库。"""

    def __init__(
        self,
        rules: RulesBundle,
        book: UnitsBook,
        store=None,  # MatchStore | None
        hud: HUDBase | None = None,
    ) -> None:
        self._rules = rules
        self._book = book
        self._store = store
        self._hud = hud or ConsoleHUD(quiet=True)
        self._layers_mod = LayerProgress(build_rewards_map(rules.rewards))
        self._power = PowerScorer(book)
        self._guard = LayersGuard()
        self._match_id: int | None = None
        self._version = rules.patch
        # hp 历史窗口（trend 分量与断连推演用）
        self._hp_history: list[int] = []
        self._store_warned = False  # E7 Toast 只提示一次

    # ---------- 对局生命周期 ----------

    def start_match(self, version: str | None = None) -> int:
        """开新局：建 match 行。返回 match_id。version 预留多版本库切换。"""
        if self._store is not None:
            self._match_id = self._store.start_match()
        else:
            self._match_id = 0  # 内存模式
        self._layers_mod = LayerProgress(
            build_rewards_map(self._rules.rewards)
        )  # 重置 once 去重
        self._guard.reset()
        self._hp_history.clear()
        return self._match_id

    def resume_match(self, match_id: int) -> None:
        """断线续采：挂到既有 match（US-6b）。"""
        self._match_id = match_id

    # ---------- 主流程 ----------

    def on_round(
        self,
        snap: BoardSnapshot,
        players: dict[str, PlayerState] | None = None,
        next_opp: str | None = None,
        task: TaskState | None = None,
    ) -> list:
        """单回合决策。返回 Advice 列表（silent 时为空）。"""
        from tft_copilot.decision.snapshot import Advice

        t0 = time.perf_counter()
        advices: list[Advice] = []

        # 0. 质量门卫（E1）
        if not quality_gate(snap.quality):
            self._push_hud_silent(snap)
            return []

        # 1. 层数卫兵（E2）
        layers = self._guard.track(snap.layers)
        if layers is not None and snap.hp is not None:
            self._hp_history.append(snap.hp)
            if len(self._hp_history) > 6:
                self._hp_history.pop(0)

        # 2. 模块(1) 层数进度
        advices += self._layers_mod.on_layers(layers, snap.hp)

        # 3. 模块(2) 战力评分（8家）
        scores: dict[str, float | None] = {}
        if players:
            for name, ps in players.items():
                scores[name] = self._power.score(ps)

        # 4. 模块(3) 对位预测
        my_score = scores.get("me")
        opp_score = scores.get(next_opp) if next_opp else None
        pred = predict(my_score, opp_score)
        advices += advice_for(pred, next_opp)

        # 5. 模块(4) 影响推演
        nxt = self._rules.next_reward(layers) if layers is not None else None
        advices += impact_evaluate(
            pred,
            task,
            layers,
            nxt.layers if nxt else None,
            " / ".join(nxt.options) if nxt else None,
        )

        # 6. 去重（同 source + 前 12 字相同视为重复）
        advices = self._dedup(advices)

        # 7. HUD
        self._hud.update(self._hud_state(snap, layers, scores))

        # 8. 落库（E7 降级）
        self._store_round(snap, layers, my_score, next_opp, pred, advices)

        self._last_cost_ms = (time.perf_counter() - t0) * 1000
        return advices

    # ---------- 辅助 ----------

    def _hud_state(
        self,
        snap: BoardSnapshot,
        layers: int | None,
        scores: dict[str, float | None],
    ) -> HUDState:
        nxt = None
        dist = None
        if layers is not None:
            for m in MILESTONES:
                if m > layers:
                    nxt = m
                    dist = m - layers
                    break
        ordered = sorted(scores.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0)))
        return HUDState(
            layers=layers,
            next_milestone=nxt,
            dist_to_milestone=dist,
            players=ordered,
            match_id=self._match_id,
            round_no=snap.round_no,
        )

    @staticmethod
    def _dedup(advices: list) -> list:
        seen: set[str] = set()
        out = []
        for a in advices:
            key = f"{a.source}:{a.text[:12]}"
            if key not in seen:
                seen.add(key)
                out.append(a)
        return out

    def _store_round(self, snap, layers, my_score, next_opp, pred, advices) -> None:
        if self._store is None or self._match_id is None:
            return
        try:
            self._store.record_round(
                self._match_id,
                snap.round_no,
                snap.scene,
                snap.quality,
                layers,
                snap.hp,
                snap.gold,
                snap.level,
                snap.trusted_units(),
                my_score,
                next_opp,
                pred.winrate,
                pred.confidence,
                advices,
            )
        except Exception:
            # E7：文件锁等 -> 内存模式，Toast 一次
            self._store = None
            if not self._store_warned:
                self._hud.toast("warn", "数据落库暂不可用（已切内存模式）")
                self._store_warned = True

    def _push_hud_silent(self, snap: BoardSnapshot) -> None:
        """E1 Silent：只保活 HUD 状态，不出建议。"""
        self._hud.update(
            HUDState(match_id=self._match_id, round_no=snap.round_no)
        )

    # ---------- 复盘 ----------

    def record_result(self, round_no: int, result: str) -> None:
        if self._store is not None and self._match_id is not None:
            self._store.record_result(self._match_id, round_no, result)

    def close_match(
        self, final_place: int | None, final_layers: int | None, win_loss: str
    ) -> None:
        if self._store is not None and self._match_id is not None:
            self._store.close_match(self._match_id, final_place, final_layers, win_loss)

    @property
    def last_cost_ms(self) -> float:
        return getattr(self, "_last_cost_ms", 0.0)
