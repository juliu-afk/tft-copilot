"""M1-2 弈子数值库加载器：三重校验 + 查询接口.

与 rules_loader.py 同构（M1-1 已验证模式）：
- 三重版本校验：文件名版本 ↔ meta.patch ↔ schema_version
- 异常体系共用 KnowledgeError 基类
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "units"

EXPECTED_SCHEMA_VERSION = 2
QUALITY_FLAGS_ENUM = {
    "duplicate_star_rows",
    "skill_scale_mismatch",
    "missing_skill_scale",
    "manual_fix",
}


class KnowledgeError(Exception):
    """知识库数据错误基类（rules/units 共用）。"""


class UnitsDataError(KnowledgeError):
    """units 数值库数据错误。"""


@dataclass(frozen=True)
class StarRow:
    star: int
    hp: int
    ad: int
    ar: int
    mr: int
    crit: float | None


@dataclass(frozen=True)
class Skill:
    name: str | None
    type: str | None
    detail: str | None
    scales: tuple[str, ...]


@dataclass(frozen=True)
class Unlock:
    is_unlockable: bool
    condition: str | None
    price: int | None


@dataclass(frozen=True)
class Unit:
    id: str
    name: str
    alias: tuple[str, ...]
    cost: int
    traits: tuple[str, ...]
    attack_speed: float | None
    range: int | None
    mana_start: int | None
    mana_max: int | None
    crit: float | None
    stars: tuple[StarRow, ...]
    skill: Skill
    unlock: Unlock
    quality_flags: tuple[str, ...]

    @property
    def star1(self) -> StarRow:
        return self.stars[0]

    @property
    def star_top(self) -> StarRow:
        """最高档星级行（原始行序的最后一行，含重复行时不影响取顶档）。"""
        return self.stars[-1]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise UnitsDataError(msg)


def _parse_unit(raw: dict[str, Any]) -> Unit:
    _require(isinstance(raw.get("id"), str) and raw["id"], "unit.id 缺失或非字符串")
    _require(isinstance(raw.get("name"), str) and raw["name"], f"[{raw.get('id')}] name 缺失")
    _require(isinstance(raw.get("cost"), int) and 1 <= raw["cost"] <= 5, f"[{raw['id']}] cost 非法")

    stars = []
    for i, s in enumerate(raw.get("stars", []), 1):
        star_no = s.get("star", i)
        _require(
            isinstance(star_no, int) and not isinstance(star_no, bool) and star_no >= 1,
            f"[{raw['id']}] 星级行 star 非法: {star_no!r}（须 ≥1 整数）",
        )
        _require(
            all(isinstance(s.get(k), int) and s[k] >= 0 for k in ("hp", "ad", "ar", "mr")),
            f"[{raw['id']}] 星级行 {star_no} 五维不完整（hp/ad/ar/mr 必须非负整数）",
        )
        stars.append(
            StarRow(
                star=star_no,
                hp=s["hp"],
                ad=s["ad"],
                ar=s["ar"],
                mr=s["mr"],
                crit=s.get("crit"),
            )
        )
    _require(bool(stars), f"[{raw['id']}] stars 为空")

    skill_raw = raw.get("skill") or {}
    skill = Skill(
        name=skill_raw.get("name"),
        type=skill_raw.get("type"),
        detail=skill_raw.get("detail"),
        scales=tuple(skill_raw.get("scales") or ()),
    )
    unlock_raw = raw.get("unlock") or {}
    unlock = Unlock(
        is_unlockable=bool(unlock_raw.get("is_unlockable")),
        condition=unlock_raw.get("condition"),
        price=unlock_raw.get("price"),
    )

    return Unit(
        id=raw["id"],
        name=raw["name"],
        alias=tuple(raw.get("alias") or ()),
        cost=raw["cost"],
        traits=tuple(raw.get("traits") or ()),
        attack_speed=raw.get("attack_speed"),
        range=raw.get("range"),
        mana_start=raw.get("mana_start"),
        mana_max=raw.get("mana_max"),
        crit=raw.get("crit"),
        stars=tuple(stars),
        skill=skill,
        unlock=unlock,
        quality_flags=tuple(raw.get("quality_flags") or ()),
    )


class UnitsBook:
    """units_18.6.json 的内存视图：加载时强校验，查询接口零拷贝."""

    @classmethod
    def from_file(cls, path: str | Path) -> UnitsBook:
        p = Path(path)
        with p.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls(payload, str(p))

    def __init__(self, payload: dict[str, Any], source_file: str):
        self._source = source_file
        self._payload = payload
        errors = self._validate(payload, source_file)
        if errors:
            raise UnitsDataError("; ".join(errors[:5]) + (f"（共 {len(errors)} 处）" if len(errors) > 5 else ""))
        self.meta: dict[str, Any] = payload["meta"]
        self.redundant_ids: list[list[str]] = payload.get("redundant_ids", [])
        self._by_id: dict[str, Unit] = {u.id: u for u in (_parse_unit(r) for r in payload["units"])}
        self._redundant_second_ids = {pair[1] for pair in self.redundant_ids}

    # ---------- 校验 ----------

    @staticmethod
    def _validate(payload: dict[str, Any], source_file: str) -> list[str]:
        errors: list[str] = []
        if payload.get("schema_version") != EXPECTED_SCHEMA_VERSION:
            errors.append(f"schema_version 应为 {EXPECTED_SCHEMA_VERSION}，实际 {payload.get('schema_version')}")
        meta = payload.get("meta") or {}
        fname = Path(source_file).stem
        patch = meta.get("patch")
        if not patch or not fname.endswith(patch):
            errors.append(f"三重校验失败：文件名 {fname} 与 meta.patch {patch} 不一致")
        units = payload.get("units")
        if not isinstance(units, list) or not units:
            errors.append("units 数组缺失或为空")
            return errors
        ids = [u.get("id") for u in units]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errors.append(f"ID 重复：{sorted(dup)[:5]}")
        if meta.get("entry_count") != len(units):
            errors.append(f"entry_count={meta.get('entry_count')} 与实际 {len(units)} 不一致")
        for pair in payload.get("redundant_ids", []):
            if len(pair) != 2 or pair[0] not in ids or pair[1] not in ids:
                errors.append(f"redundant_ids 引用不存在的 ID：{pair}")
            elif pair[0] == pair[1]:
                errors.append(f"redundant_ids 自引用：{pair}")
        for u in units:
            for f in u.get("quality_flags") or []:
                if f not in QUALITY_FLAGS_ENUM:
                    errors.append(f"[{u.get('id')}] 未知 quality_flag：{f}")
        return errors

    # ---------- 查询 ----------

    def get_unit(self, unit_id: str) -> Unit:
        try:
            return self._by_id[unit_id]
        except KeyError:
            raise UnitsDataError(f"不存在 ID {unit_id}") from None

    def find_by_name(self, name: str) -> list[Unit]:
        return [u for u in self._by_id.values() if u.name == name or name in u.alias]

    def units_by_cost(self, cost: int) -> list[Unit]:
        return [u for u in self._by_id.values() if u.cost == cost]

    def units_by_trait(self, trait: str) -> list[Unit]:
        return [u for u in self._by_id.values() if trait in u.traits]

    def dedup_view(self) -> list[Unit]:
        return [u for u in self._by_id.values() if u.id not in self._redundant_second_ids]

    def trait_registry(self) -> dict[str, int]:
        reg: dict[str, int] = {}
        for u in self.dedup_view():
            for t in u.traits:
                reg[t] = reg.get(t, 0) + 1
        return reg

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self):
        return iter(self._by_id.values())
