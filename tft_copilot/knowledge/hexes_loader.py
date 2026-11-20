# -*- coding: utf-8 -*-
"""强化符文知识加载器（2026-11-20 转正，源：jinchanchan.fun hex API 297 条）.

档位映射：level 1=银 2=金 3=彩 4=独特。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HexEntry:
    id: int
    name: str
    tier: str          # 银/金/彩/独特
    level: int         # 1-4
    desc: str
    tags: list[str] = field(default_factory=list)

    @property
    def is_prismatic(self) -> bool:
        return self.level >= 3


class HexesBook:
    def __init__(self, hexes: list[HexEntry]):
        self._by_name = {h.name: h for h in hexes}
        self._by_tier: dict[str, list[HexEntry]] = {}
        for h in hexes:
            self._by_tier.setdefault(h.tier, []).append(h)
        self.count = len(hexes)

    def find(self, name: str) -> HexEntry | None:
        return self._by_name.get(name)

    def by_tier(self, tier: str) -> list[HexEntry]:
        return self._by_tier.get(tier, [])

    def search(self, keyword: str) -> list[HexEntry]:
        return [h for h in self._by_name.values() if keyword in h.name or keyword in h.desc]


def load_hexes(path: Path | None = None) -> HexesBook:
    from tft_copilot.paths import bundle_data_dir

    if path is None:
        path = bundle_data_dir() / "hexes" / "hexes_18.6.json"
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    hexes = [
        HexEntry(
            id=d["id"], name=d["name"], tier=d["tier"],
            level=d["level"], desc=d["desc"], tags=d.get("tags", []),
        )
        for d in raw["hexes"]
    ]
    return HexesBook(hexes)
