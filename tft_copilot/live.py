"""实时副官：截屏循环 → 场景识别 → 决策 → HUD（M6 前置最小入口）.

红线自查：零输入模拟（只截屏读像素）、零进程读取、零网络。

用法：
    python -m tft_copilot live          # 源码运行
    双击 tft-copilot.exe 选 [1]         # exe 运行

循环骨架（工程方案 7.2 分频调度）：
    grab -> detect scene -> 按场景分频 -> 数字 ROI + 弈子识别 ->
    BoardSnapshot -> DecisionEngine.on_round -> advices -> HUD

诚实原则：
- 识别失败字段保持 None（决策层自带降级链）；
- UNKNOWN/PRE_GAME 空转不喂决策层（防桌面误识别污染对局库）；
- 首次进入对局场景自动 start_match，Ctrl+C 退出收尾。
"""

from __future__ import annotations

import json
import time

import numpy as np

from tft_copilot.decision.engine import DecisionEngine
from tft_copilot.decision.snapshot import BoardSnapshot, UnitOnBoard
from tft_copilot.knowledge.equips_loader import load_equips
from tft_copilot.knowledge.rules_loader import load_rules
from tft_copilot.knowledge.traits_loader import load_traits
from tft_copilot.knowledge.units_loader import UnitsBook
from tft_copilot.overlay.hud import HUDState, create_hud
from tft_copilot.paths import writable_data_dir
from tft_copilot.perception.grabber import ScreenGrabber
from tft_copilot.perception.numbers import read_number
from tft_copilot.perception.scene import GameScene, SceneScheduler
from tft_copilot.perception.templates import TEMPLATES_DIR, TemplateBank
from tft_copilot.perception.units_spotter import UnitSpotter
from tft_copilot.store.db import MatchStore

NUM_KEYS = ("layer", "gold", "hp", "level")


def load_anchors_config(patch: str = "18.6") -> dict:
    """读 anchors.json（ROI 坐标表）。"""
    f = TEMPLATES_DIR / f"v{patch}" / "anchors.json"
    return json.loads(f.read_text(encoding="utf-8"))


class LiveCopilot:
    """实时副官会话：start_live() 即一局。"""

    def __init__(self, db_path=None, quiet: bool = False) -> None:
        self._quiet = quiet
        self._db_path = db_path
        self._store: MatchStore | None = (
            MatchStore(db_path, "18.6") if db_path is not None else None
        )
        # 感知组件
        self._bank = TemplateBank()
        self._scheduler = SceneScheduler()
        self._spotter = UnitSpotter(bank=self._bank)
        self._grabber = ScreenGrabber()
        self._anchors = load_anchors_config()
        # 决策组件
        self._book = UnitsBook.from_file(writable_data_dir() / "units" / "units_18.6.json")
        self._engine = DecisionEngine(
            load_rules(),
            self._book,
            store=self._store,
            hud=None,
            traits_book=load_traits(),
            equips_book=load_equips(),
        )
        # 会话状态
        self._match_id: int | None = None
        self._round_no = 0
        self._last_scene = GameScene.UNKNOWN
        self._shutdown = False
        self._hud = None

    # ---------- 感知 ----------

    def _read_numbers(self, frame: np.ndarray) -> dict[str, int | None]:
        """读 4 个数字 ROI；失败为 None（诚实降级）。"""
        out: dict[str, int | None] = {}
        rois = self._anchors.get("numbers", {})
        for name in NUM_KEYS:
            spec = rois.get(name)
            if spec is None:
                out[name] = None
                continue
            try:
                out[name] = read_number(frame, tuple(spec["roi"]), self._bank)
            except Exception:
                out[name] = None
        return out

    def _spot_units(self, frame: np.ndarray, scene: GameScene) -> list[UnitOnBoard]:
        """识别自家弈子：SHOP 查商店 5 卡位；BATTLE 查棋盘+板凳。"""
        rois = self._anchors.get("units", {})
        groups: list[tuple[int, int, int, int]] = []
        if scene == GameScene.SHOP:
            groups = [tuple(r) for r in rois.get("shop5", {}).get("rois", [])]
        elif scene == GameScene.BATTLE:
            for key in ("board", "bench"):
                groups.extend(tuple(r) for r in rois.get(key, {}).get("rois", []))
        out: list[UnitOnBoard] = []
        for area in groups:
            try:
                boxes = self._spotter.spot(frame, area)
            except Exception:
                continue
            for b in boxes:
                out.append(
                    UnitOnBoard(
                        unit_id=b.unit_id, cost=b.cost, star=b.star, score=b.score, items=()
                    )
                )
        return out

    # ---------- 决策 ----------

    def _maybe_new_round(self, scene: GameScene) -> None:
        """场景切到 BATTLE = 新回合边界。"""
        if scene != self._last_scene and scene == GameScene.BATTLE:
            self._round_no += 1

    def _ensure_match(self) -> None:
        if self._match_id is None and self._store is not None:
            self._match_id = self._engine.start_match()

    def _feed_engine(self, nums: dict, units: list[UnitOnBoard], scene: GameScene) -> list:
        self._ensure_match()
        snap = BoardSnapshot(
            round_no=self._round_no,
            scene=scene.value,
            quality=0.8,  # 真机质量门 M6 校准（TH=0.3 先放行）
            my_units=units,
            layers=nums.get("layer"),
            hp=nums.get("hp"),
            gold=nums.get("gold"),
            level=nums.get("level"),
        )
        return self._engine.on_round(snap)

    # ---------- HUD ----------

    def _push_hud(self, nums: dict, advices: list) -> None:
        state = HUDState(
            layers=nums.get("layer"),
            round_no=self._round_no,
            match_id=self._match_id,
        )
        if self._hud is not None:
            self._hud.update(state)
            for a in advices:
                self._hud.toast(a.level, a.text)
        if not self._quiet:
            line = (
                f"\r[{time.strftime('%H:%M:%S')}] R{self._round_no}"
                f" 层{nums.get('layer') if nums.get('layer') is not None else '?'}"
                f" 金{nums.get('gold') if nums.get('gold') is not None else '?'}"
                f" 血{nums.get('hp') if nums.get('hp') is not None else '?'}"
                f" 级{nums.get('level') if nums.get('level') is not None else '?'}   "
            )
            print(line, end="", flush=True)
            for a in advices:
                print(f"\n  [{a.level}] {a.text}", flush=True)

    def _idle_hint(self, scene: GameScene) -> None:
        if self._quiet:
            return
        hint = "等待对局（未识别到游戏画面）" if scene == GameScene.UNKNOWN else "游戏大厅，未开局"
        print(f"\r[{time.strftime('%H:%M:%S')}] {hint}   ", end="", flush=True)

    # ---------- 主循环 ----------

    def _poll_once(self) -> float:
        """跑一帧，返回本帧应 sleep 秒数。"""
        frame = self._grabber.grab()
        scene = self._scheduler.detect(frame)
        interval = self._scheduler.poll_interval(scene)
        if scene in (GameScene.UNKNOWN, GameScene.PRE_GAME):
            self._idle_hint(scene)
            return interval
        nums = self._read_numbers(frame)
        units = self._spot_units(frame, scene)
        self._maybe_new_round(scene)
        advices = self._feed_engine(nums, units, scene)
        self._push_hud(nums, advices)
        self._last_scene = scene
        return interval

    def start_live(self, max_seconds: float | None = None) -> dict:
        """主循环：Ctrl+C 优雅退出，返回统计。"""
        qt_app = None
        hud = None
        if not self._quiet:
            try:  # Overlay HUD（Qt 事件泵由本循环驱动）
                from PyQt6.QtWidgets import QApplication

                qt_app = QApplication.instance() or QApplication([])
                hud = create_hud("overlay")
            except Exception:
                hud = None
        if hud is None:
            hud = create_hud("console")
        self._hud = hud

        started = time.perf_counter()
        stats: dict = {"frames": 0, "advices": 0, "scenes": {}, "duration": 0.0}
        if not self._quiet:
            print("== tft-copilot 实时副官 ==")
            print("进对局自动开跑；Ctrl+C 退出")
        try:
            while not self._shutdown:
                if max_seconds is not None and time.perf_counter() - started >= max_seconds:
                    break
                t0 = time.perf_counter()
                try:
                    interval = self._poll_once()
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # 单帧失败不终止循环
                    interval = 1.0
                    if not self._quiet:
                        print(f"\n[warn] 帧异常: {exc}", flush=True)
                stats["frames"] += 1
                s = self._last_scene.value
                stats["scenes"][s] = stats["scenes"].get(s, 0) + 1
                if qt_app is not None:
                    qt_app.processEvents()
                elapsed = time.perf_counter() - t0
                time.sleep(max(0.0, interval - elapsed))
        except KeyboardInterrupt:
            if not self._quiet:
                print("\n收到退出信号")
        finally:
            stats["duration"] = round(time.perf_counter() - started, 1)
            if hud is not None:
                try:
                    hud.close()
                except Exception:
                    pass
            if self._store is not None:
                try:
                    self._store.close()
                except Exception:
                    pass
        if not self._quiet:
            print(f"\n== 会话结束 {stats['duration']}s {stats['frames']} 帧 ==")
            top = sorted(stats["scenes"].items(), key=lambda kv: -kv[1])[:4]
            print("场景分布:", ", ".join(f"{k}x{v}" for k, v in top))
        return stats

    def stop(self) -> None:
        self._shutdown = True


def start_live_command(max_seconds: float | None = None, quiet: bool = False) -> dict:
    """live 子命令入口（CLI/exe 共用）：路径重定向 + 落库。"""
    from tft_copilot.paths import patch_data_paths

    wroot = patch_data_paths()
    db = wroot / "db" / "matches_v18.6.db"
    return LiveCopilot(db_path=db, quiet=quiet).start_live(max_seconds=max_seconds)
