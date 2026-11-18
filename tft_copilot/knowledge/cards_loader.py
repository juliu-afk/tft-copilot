"""时间卡片库加载器（M4）。

铁律对齐 units_loader：三重校验（文件名版本 == meta.patch == 库规模预期）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATCH = "18.6"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "cards" / f"cards_{DEFAULT_PATCH}.json"

KNOWN_TAGS = frozenset(
    {
        "economy",
        "xp",
        "trait-bridge",
        "combat",
        "sustain",
        "reroll",
        "item",
        "copy",
        "generic",
    }
)


class CardsDataError(Exception):
    """卡片库数据不合法。"""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise CardsDataError(msg)


@dataclass(frozen=True)
class TimeCard:
    """时间卡片条目。"""

    id: int
    name: str
    star: int
    icon: str
    effect_desc: str | None
    effect_tags: tuple[str, ...]
    energy_cost: int | None
    quality_flags: tuple[str, ...]


@dataclass
class CardsBook:
    """201 张时间卡的可检索集合。"""

    cards: list[TimeCard]
    patch: str
    star_dist: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._index = {c.id: c for c in self.cards}

    def __len__(self) -> int:
        return len(self.cards)

    def __iter__(self):
        return iter(self.cards)

    def by_id(self, cid: int) -> TimeCard:
        try:
            return self._index[cid]
        except KeyError:
            raise CardsDataError(f"卡片不存在: {cid}") from None

    def by_star(self, star: int) -> list[TimeCard]:
        return [c for c in self.cards if c.star == star]

    def by_tag(self, tag: str) -> list[TimeCard]:
        return [c for c in self.cards if tag in c.effect_tags]

    def stats(self) -> str:
        return "卡池 {n} 张 / 星级分布 {d}".format(
            n=len(self.cards),
            d=" ".join(f"{k}星{v}" for k, v in sorted(self.star_dist.items())),
        )


def load_cards(path: str | Path | None = None, patch: str = DEFAULT_PATCH) -> CardsBook:
    """加载并三重校验。文件名版本必须与请求 patch 一致，meta.patch 必须一致。"""
    p = Path(path) if path else DEFAULT_PATH
    if patch not in p.name:
        raise CardsDataError(f"文件名版本不匹配: {p.name} 不含 {patch}（版本化铁律）")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CardsDataError(f"卡片库不存在: {p}") from None
    except json.JSONDecodeError as e:
        raise CardsDataError(f"卡片库 JSON 解析失败: {e}") from None

    meta = raw.get("meta") or {}
    _require(meta.get("patch") == patch, f"meta.patch={meta.get('patch')!r} != {patch!r}")
    cards_raw = raw.get("cards")
    _require(isinstance(cards_raw, list) and len(cards_raw) > 0, "cards 数组为空或缺失")

    cards: list[TimeCard] = []
    seen: set[int] = set()
    dist: dict[int, int] = {}
    for c in cards_raw:
        cid = c.get("id")
        _require(isinstance(cid, int) and not isinstance(cid, bool), f"卡片 id 非法: {cid!r}")
        _require(cid not in seen, f"卡片 id 重复: {cid}")
        seen.add(cid)
        name = c.get("name")
        _require(isinstance(name, str) and name.strip(), f"[{cid}] name 为空")
        star = c.get("star")
        _require(
            isinstance(star, int) and not isinstance(star, bool) and 1 <= star <= 5,
            f"[{cid}] star 非法: {star!r}（须 1-5）",
        )
        tags = tuple(c.get("effect_tags") or ["generic"])
        unknown = [t for t in tags if t not in KNOWN_TAGS]
        _require(not unknown, f"[{cid}] 未知 effect_tags: {unknown}")
        desc = c.get("effect_desc")
        _require(desc is None or isinstance(desc, str), f"[{cid}] effect_desc 类型非法")
        energy = c.get("energy_cost")
        _require(energy is None or isinstance(energy, int), f"[{cid}] energy_cost 类型非法")
        cards.append(
            TimeCard(
                id=cid,
                name=name,
                star=star,
                icon=str(c.get("icon") or ""),
                effect_desc=desc,
                effect_tags=tags,
                energy_cost=energy,
                quality_flags=tuple(c.get("quality_flags") or []),
            )
        )
        dist[star] = dist.get(star, 0) + 1

    meta_dist = meta.get("star_dist") or {}
    _require(
        {int(k): v for k, v in meta_dist.items()} == dist,
        f"meta.star_dist 与实际分布不一致: {meta_dist} vs {dist}",
    )
    return CardsBook(cards=cards, patch=patch, star_dist=dist)


def desc_review_list(book: CardsBook) -> list[dict]:
    """输出待人工校验清单（desc_missing 卡）。"""
    return [
        {"id": c.id, "name": c.name, "star": c.star, "effect_tags": list(c.effect_tags)}
        for c in book.cards
        if "desc_missing" in c.quality_flags
    ]


def _self_check() -> None:  # pragma: no cover - 开发期自检
    book = load_cards()
    assert len(book) == 201, len(book)
    assert book.star_dist == {1: 20, 2: 30, 3: 60, 4: 50, 5: 41}, book.star_dist
    assert len(desc_review_list(book)) == 201  # 当前全部 desc_missing
    names = [c.name for c in book]
    assert len(set(names)) == 201, "重名"
    assert re.match(r"^\d+$", str(book.cards[0].id))
    print("cards self-check OK:", book.stats())


if __name__ == "__main__":  # pragma: no cover
    _self_check()
