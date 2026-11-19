"""装备数值库加载器（M5）。

铁律对齐 units/traits/cards loader：三重校验（文件名版本 == meta.patch == 规模）。
红线自查：零网络、零输入模拟、零进程读取。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATCH = "18.6"
DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "equips" / f"equips_{DEFAULT_PATCH}.json"
)

# 六类装备类型枚举（与 GRADE_BY_TYPE 一一对应，校验用）
VALID_TYPES = frozenset(
    {"成型装备", "光明武器", "神器装备", "转职纹章", "特殊装备", "基础装备"}
)


class EquipsDataError(Exception):
    """装备库数据不合法。"""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise EquipsDataError(msg)


@dataclass(frozen=True)
class Equip:
    """装备条目。grade: 强度权重（成装 1.0 锚点）；synth: 合成路径（组件 id）。"""

    id: int
    name: str
    type: str
    grade: float
    synth: tuple[int, ...]
    desc: str


@dataclass(frozen=True)
class EquipsBook:
    """装备库：全量 tuple + id 索引。"""

    equips: tuple[Equip, ...]
    patch: str
    version_id: str
    _index: dict[int, Equip] = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._index is None:
            object.__setattr__(self, "_index", {e.id: e for e in self.equips})

    def by_id(self, equip_id: int) -> Equip:
        """按 id 查装备；未知 id 抛 EquipsDataError（调用方负责降级）。"""
        try:
            return self._index[equip_id]
        except KeyError as err:
            raise EquipsDataError(f"未知装备 id: {equip_id}") from err

    def __iter__(self):
        return iter(self.equips)

    def __len__(self) -> int:
        return len(self.equips)


def load_equips(path: Path | str | None = None, patch: str = DEFAULT_PATCH) -> EquipsBook:
    """加载 + 三重校验。文件名版本 / meta.patch / 数据规模三者必须一致。"""
    p = Path(path) if path is not None else DEFAULT_PATH
    if not p.exists():
        raise EquipsDataError(f"装备库不存在: {p}")
    stem_patch = p.stem.rsplit("_", 1)[-1]
    _require(stem_patch == patch, f"文件名版本 {stem_patch} != 请求版本 {patch}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise EquipsDataError(f"JSON 解析失败: {err}") from err
    meta = raw.get("meta", {})
    _require(meta.get("patch") == patch, f"meta.patch {meta.get('patch')!r} != {patch}")
    items = raw.get("equips", [])
    _require(
        meta.get("count") == len(items),
        f"meta.count {meta.get('count')} != 实际 {len(items)}",
    )
    equips: list[Equip] = []
    seen_ids: set[int] = set()
    for it in items:
        _require(
            it.get("type") in VALID_TYPES, f"装备 {it.get('id')} 类型非法: {it.get('type')!r}"
        )
        _require(
            isinstance(it.get("grade"), (int, float)) and it.get("grade", 0) > 0,
            f"装备 {it.get('id')} grade 非法: {it.get('grade')!r}",
        )
        _require(bool(it.get("name")), f"装备 {it.get('id')} 缺 name")
        _require(it["id"] not in seen_ids, f"装备 id 重复: {it['id']}")
        seen_ids.add(it["id"])
        equips.append(
            Equip(
                id=it["id"],
                name=it["name"],
                type=it["type"],
                grade=float(it["grade"]),
                synth=tuple(it.get("synth", [])),
                desc=it.get("desc", ""),
            )
        )
    return EquipsBook(
        equips=tuple(equips),
        patch=str(meta.get("patch", patch)),
        version_id=str(meta.get("version_id", "")),
    )
