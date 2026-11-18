"""知识层：静态规则库加载器。

职责：加载 data/rules/rules_{patch}.json，执行三重版本校验（v1.1 P0-2），
提供任务/奖励/钥匙/路线的查询接口。

红线自查：本模块零网络、零进程读取、零输入模拟——纯本地 JSON 消费。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RulesValidationError",
    "VersionMismatchError",
    "SchemaVersionError",
    "Task",
    "Reward",
    "Key",
    "Route",
    "RulesBundle",
    "load_rules",
]

SUPPORTED_SCHEMA_VERSION = 1
VALID_TIERS = {"good", "warn", "bad"}
VALID_CATEGORIES = {"economy", "combat", "streak", "risk", "milestone", "bench"}
VALID_QUALITIES = {"weak", "normal", "strong", "jackpot"}


class RulesValidationError(Exception):
    """规则库校验失败（缺字段/非法枚举/引用悬空等）。"""


class VersionMismatchError(RulesValidationError):
    """meta.patch 与文件名版本不一致。"""


class SchemaVersionError(RulesValidationError):
    """schema_version 高于加载器支持版本。"""


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Variant:
    stage: int
    requirement: str
    layers: int


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    name: str
    category: str
    tier: str
    tier_note: str
    routes: tuple[str, ...]
    variants: tuple[Variant, ...]

    def variant_at(self, stage: int) -> Variant | None:
        for v in self.variants:
            if v.stage == stage:
                return v
        return None


@dataclass(frozen=True, slots=True)
class Reward:
    layers: int
    options: tuple[str, ...]
    quality: str
    note: str


@dataclass(frozen=True, slots=True)
class Key:
    id: str
    name: str
    unlock: str
    effects: tuple[str, ...]
    strategy: str


@dataclass(frozen=True, slots=True)
class Route:
    id: str
    name: str
    condition: str
    stage_23_tasks: tuple[str, ...]
    stage_45_tasks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RulesBundle:
    patch: str
    tasks: dict[str, Task] = field(default_factory=dict)
    rewards: tuple[Reward, ...] = ()
    keys: tuple[Key, ...] = ()
    routes: dict[str, Route] = field(default_factory=dict)

    # -- 查询接口 -----------------------------------------------------------

    def get_task(self, task_id: str) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError:
            raise KeyError(f"任务不存在: {task_id}") from None

    def tasks_by_stage_route(self, stage: int, route: str) -> list[Task]:
        """路线推荐序列 ∩ 该阶段有变体的任务，按推荐顺序返回。

        stage 2-3 取 stage_23_tasks，stage 4-6 取 stage_45_tasks。
        """
        r = self.routes[route]
        seq = r.stage_23_tasks if stage <= 3 else r.stage_45_tasks
        out: list[Task] = []
        for tid in seq:
            t = self.tasks[tid]
            if t.variant_at(stage) is not None:
                out.append(t)
        return out

    def tasks_by_tier(self, tier: str, stage: int | None = None) -> list[Task]:
        """按评级筛选；stage 给定时仅保留该阶段有变体的任务。"""
        if tier not in VALID_TIERS:
            raise ValueError(f"非法评级: {tier}，可选 {sorted(VALID_TIERS)}")
        out = []
        for t in self.tasks.values():
            if t.tier != tier:
                continue
            if stage is not None and t.variant_at(stage) is None:
                continue
            out.append(t)
        return out

    def next_reward(self, current_layers: int) -> Reward | None:
        """首个 layers > current 的奖励档；到顶返回 None。"""
        for r in self.rewards:
            if r.layers > current_layers:
                return r
        return None

    def reward_at(self, layers: int) -> Reward | None:
        """档位精确查询。"""
        for r in self.rewards:
            if r.layers == layers:
                return r
        return None


# ---------------------------------------------------------------------------
# 加载与校验
# ---------------------------------------------------------------------------


def _rules_dir(data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        return data_dir
    # 包内定位：tft_copilot/knowledge/ → 仓库根 data/rules/
    return Path(__file__).resolve().parents[2] / "data" / "rules"


def _build_task(raw: dict) -> Task:
    variants_raw = raw.get("variants")
    if not variants_raw or not isinstance(variants_raw, list):
        raise RulesValidationError(f"任务 {raw.get('id', '?')} variants 缺失或为空")
    stages: list[int] = []
    variants: list[Variant] = []
    for v in variants_raw:
        stage = v.get("stage")
        if not isinstance(stage, int) or not (2 <= stage <= 6):
            raise RulesValidationError(f"任务 {raw.get('id', '?')} variant.stage 非法: {stage}")
        if stages and stage <= stages[-1]:
            raise RulesValidationError(
                f"任务 {raw.get('id', '?')} variants.stage 必须升序: {stages + [stage]}"
            )
        stages.append(stage)
        layers = v.get("layers")
        if not isinstance(layers, int) or layers <= 0:
            raise RulesValidationError(f"任务 {raw.get('id', '?')} stage{stage} layers 非法: {layers}")
        req = v.get("requirement")
        if not req or not isinstance(req, str):
            raise RulesValidationError(f"任务 {raw.get('id', '?')} stage{stage} requirement 缺失")
        variants.append(Variant(stage=stage, requirement=req, layers=layers))
    tier = raw.get("tier")
    if tier not in VALID_TIERS:
        raise RulesValidationError(f"任务 {raw.get('id', '?')} tier 非法: {tier}")
    category = raw.get("category")
    if category not in VALID_CATEGORIES:
        raise RulesValidationError(f"任务 {raw.get('id', '?')} category 非法: {category}")
    return Task(
        id=raw["id"],
        name=raw["name"],
        category=category,
        tier=tier,
        tier_note=raw.get("tier_note", ""),
        routes=tuple(raw.get("routes", [])),
        variants=tuple(variants),
    )


def _validate_and_build(data: dict, patch: str, source_name: str) -> RulesBundle:
    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise RulesValidationError(f"{source_name}: meta 缺失")

    # 三重校验①：文件名版本 ↔ meta.patch
    if meta.get("patch") != patch:
        raise VersionMismatchError(
            f"{source_name}: 文件名版本 {patch} != meta.patch {meta.get('patch')}"
        )

    # 三重校验③：schema_version
    sv = meta.get("schema_version")
    if not isinstance(sv, int):
        raise RulesValidationError(f"{source_name}: schema_version 缺失或非整数")
    if sv > SUPPORTED_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"{source_name}: schema_version={sv} 高于加载器支持 {SUPPORTED_SCHEMA_VERSION}"
        )

    # tasks
    tasks: dict[str, Task] = {}
    for raw in data.get("tasks", []):
        tid = raw.get("id")
        if not tid or tid in tasks:
            raise RulesValidationError(f"任务 id 缺失或重复: {tid}")
        tasks[tid] = _build_task(raw)

    # rewards：升序唯一
    rewards: list[Reward] = []
    last = 0
    for raw in data.get("rewards", []):
        layers = raw.get("layers")
        if not isinstance(layers, int) or layers <= last:
            raise RulesValidationError(f"rewards.layers 必须升序唯一: {layers}（前值 {last}）")
        opts = raw.get("options")
        if not opts or not isinstance(opts, list):
            raise RulesValidationError(f"{layers} 层奖励 options 缺失或为空")
        quality = raw.get("quality")
        if quality not in VALID_QUALITIES:
            raise RulesValidationError(f"{layers} 层奖励 quality 非法: {quality}")
        last = layers
        rewards.append(
            Reward(layers=layers, options=tuple(opts), quality=quality, note=raw.get("note", ""))
        )
    if not rewards:
        raise RulesValidationError("rewards 为空")

    # keys
    keys = tuple(
        Key(
            id=k["id"],
            name=k["name"],
            unlock=k.get("unlock", ""),
            effects=tuple(k.get("effects", [])),
            strategy=k.get("strategy", ""),
        )
        for k in data.get("keys", [])
    )

    # routes：引用完整性
    routes: dict[str, Route] = {}
    for raw in data.get("routes", []):
        rid = raw.get("id")
        if not rid or rid in routes:
            raise RulesValidationError(f"路线 id 缺失或重复: {rid}")
        for seq_key in ("stage_23_tasks", "stage_45_tasks"):
            for tid in raw.get(seq_key, []):
                if tid not in tasks:
                    raise RulesValidationError(f"路线 {rid}.{seq_key} 引用不存在的任务: {tid}")
        routes[rid] = Route(
            id=rid,
            name=raw["name"],
            condition=raw.get("condition", ""),
            stage_23_tasks=tuple(raw.get("stage_23_tasks", [])),
            stage_45_tasks=tuple(raw.get("stage_45_tasks", [])),
        )

    # tasks.routes 反向引用
    for t in tasks.values():
        for rid in t.routes:
            if rid not in routes:
                raise RulesValidationError(f"任务 {t.id}.routes 引用不存在的路线: {rid}")

    return RulesBundle(patch=patch, tasks=tasks, rewards=tuple(rewards), keys=keys, routes=routes)


def load_rules(patch: str = "18.6", data_dir: Path | None = None) -> RulesBundle:
    """加载指定版本的规则库。三重校验（文件名↔meta / 存在性 / schema_version）失败即抛错。"""
    path = _rules_dir(data_dir) / f"rules_{patch}.json"
    # 三重校验②：文件存在性
    if not path.is_file():
        raise RulesValidationError(f"规则库文件不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return _validate_and_build(data, patch, path.name)
