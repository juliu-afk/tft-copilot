"""羁绊断点表加载器（M4，补 M3 遗留缺口）。

铁律对齐 units_loader/cards_loader：三重校验。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATCH = "18.6"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "traits" / f"traits_{DEFAULT_PATCH}.json"


class TraitsDataError(Exception):
    """羁绊库数据不合法。"""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise TraitsDataError(msg)


@dataclass(frozen=True)
class TraitMember:
    """羁绊成员棋子。"""

    unit_id: int
    name: str
    price: int


@dataclass(frozen=True)
class Trait:
    """羁绊条目：断点 num_list + 效果描述 + 成员。"""

    id: str
    name: str
    type: int
    max_level: int
    num_list: tuple[int, ...]
    effect_desc: str
    members: tuple[TraitMember, ...]

    @property
    def max_breakpoint(self) -> int:
        """最高断点（满级激活数）。"""
        return self.num_list[-1] if self.num_list else 0

    def breakpoint_weight(self, active: int) -> float:
        """激活数 -> 断点权重（0..1）：达到第 k 档得 k/len。

        M3 战力评分羁绊分的升级基座：真实断点替代「激活数近似」。
        """
        if not self.num_list:
            return 0.0
        hit = sum(1 for b in self.num_list if active >= b)
        return hit / len(self.num_list)


@dataclass
class TraitsBook:
    """58 羁绊可检索集合。"""

    traits: list[Trait]
    patch: str

    def __len__(self) -> int:
        return len(self.traits)

    def __iter__(self):
        return iter(self.traits)

    def by_name(self, name: str) -> Trait:
        for t in self.traits:
            if t.name == name:
                return t
        raise TraitsDataError(f"羁绊不存在: {name}")

    def member_trait_map(self) -> dict[int, set[str]]:
        """unit_id -> 羁绊名集合。"""
        out: dict[int, set[str]] = {}
        for t in self.traits:
            for m in t.members:
                out.setdefault(m.unit_id, set()).add(t.name)
        return out


def load_traits(path: str | Path | None = None, patch: str = DEFAULT_PATCH) -> TraitsBook:
    """加载并三重校验。"""
    p = Path(path) if path else DEFAULT_PATH
    if patch not in p.name:
        raise TraitsDataError(f"文件名版本不匹配: {p.name} 不含 {patch}（版本化铁律）")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TraitsDataError(f"羁绊库不存在: {p}") from None
    except json.JSONDecodeError as e:
        raise TraitsDataError(f"羁绊库 JSON 解析失败: {e}") from None

    meta = raw.get("meta") or {}
    _require(meta.get("patch") == patch, f"meta.patch={meta.get('patch')!r} != {patch!r}")
    traits_raw = raw.get("traits")
    _require(isinstance(traits_raw, list) and len(traits_raw) > 0, "traits 数组为空或缺失")

    traits: list[Trait] = []
    seen: set[str] = set()
    for t in traits_raw:
        tid = t.get("id")
        _require(isinstance(tid, str) and tid.strip(), f"羁绊 id 非法: {tid!r}")
        _require(tid not in seen, f"羁绊 id 重复: {tid}")
        seen.add(tid)
        name = t.get("name")
        _require(isinstance(name, str) and name.strip(), f"[{tid}] name 为空")
        num_list = t.get("num_list")
        _require(
            isinstance(num_list, list) and all(isinstance(x, int) and x >= 1 for x in num_list),
            f"[{tid}] num_list 非法: {num_list!r}",
        )
        _require(
            num_list == sorted(num_list) and len(set(num_list)) == len(num_list),
            f"[{tid}] num_list 须严格递增: {num_list!r}",
        )
        members = []
        for m in t.get("members") or []:
            mid = m.get("id")
            _require(isinstance(mid, int) and mid > 0, f"[{tid}] 成员 id 非法: {mid!r}")
            members.append(
                TraitMember(unit_id=mid, name=str(m.get("name") or ""), price=int(m.get("price") or 0))
            )
        _require(len(members) > 0, f"[{tid}] members 为空")
        traits.append(
            Trait(
                id=tid,
                name=name,
                type=int(t.get("type") or 0),
                max_level=int(t.get("max_level") or len(num_list)),
                num_list=tuple(num_list),
                effect_desc=str(t.get("effect_desc") or ""),
                members=tuple(members),
            )
        )

    return TraitsBook(traits=traits, patch=patch)


def _self_check() -> None:  # pragma: no cover
    book = load_traits()
    assert len(book) == 58, len(book)
    t = book.by_name("斗士")
    assert t.num_list == (2, 4, 6), t.num_list
    assert t.breakpoint_weight(2) == 1 / 3
    assert t.breakpoint_weight(6) == 1.0
    assert t.breakpoint_weight(1) == 0.0
    assert t.max_breakpoint == 6
    mmap = book.member_trait_map()
    assert mmap.get(11402) and "斗士" in mmap[11402]
    print("traits self-check OK:", len(book), "羁绊")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
