"""M4-1 开发期数据脚本：从已抓 mech 页 + trait API 生成版本化数据文件。

白名单目录：本脚本可读写本地（不联网），主包零网络。
输入：data/pending_templates_test/mech.html + api_trait.json
输出：data/cards/cards_18.6.json + data/traits/traits_18.6.json
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "pending_templates_test"

# ---------- 时间卡片 ----------

# 名称模式 -> effect_tags（可解释的骨架规则，非自由文本）
TAG_RULES: list[tuple[str, list[str]]] = [
    (r"奖金|金币|利滚利|财源|军饷|宝箱|法球|战利品|收益", ["economy"]),
    (r"经验|升级|学徒|研究生", ["xp"]),
    (r"传送门|纹章之书|羁绊神树|自选神器|之选", ["trait-bridge"]),
    (r"援兵|军备|武装|武装机械|军火|中坚|猎手|专家|精锐|盟友|援军", ["combat"]),
    (r"治疗|护盾|圣所|庇护|回复|续航", ["sustain"]),
    (r"刷新|免费|重随|D 牌|开D|快乐开D|选秀", ["reroll"]),
    (r"装备|神器|铁匠|熔铸|锻造|反曲|散件", ["item"]),
    (r"复制|镜像|孪生", ["copy"]),
]

QUALITY_NOTE = {
    "desc_missing": "效果描述待人工校验（源站无公开 API）",
}


def parse_cards_from_mech(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    cards: list[dict] = []
    seen: set[int] = set()
    for btn in soup.find_all("button"):
        img = btn.find("img", src=lambda s: s and "tomato" in s)
        if not img:
            continue
        spans = btn.find_all("span")
        if not spans:
            continue
        name = spans[0].get_text(strip=True)
        star_txt = spans[1].get_text(strip=True).replace("星", "") if len(spans) > 1 else ""
        icon = img.get("src", "")
        m = re.search(r"/(\d+)_icon", icon)
        if not m or not star_txt.isdigit():
            continue
        cid = int(m.group(1))
        if cid in seen:
            continue
        seen.add(cid)
        tags: list[str] = []
        for pat, tag in TAG_RULES:
            if re.search(pat, name):
                tags.extend(t for t in tag if t not in tags)
        cards.append(
            {
                "id": cid,
                "name": name,
                "star": int(star_txt),
                "icon": icon,
                "effect_desc": None,
                "effect_tags": tags or ["generic"],
                "energy_cost": None,
                "quality_flags": ["desc_missing"],
            }
        )
    cards.sort(key=lambda c: (c["star"], c["id"]))
    return cards


def build_cards_json() -> dict:
    html = (SRC / "mech.html").read_text(encoding="utf-8")
    cards = parse_cards_from_mech(html)
    dist = {}
    for c in cards:
        dist[c["star"]] = dist.get(c["star"], 0) + 1
    return {
        "meta": {
            "patch": "18.6",
            "mode": "大橘大利",
            "source": "jinchanchan.fun/hero/mech",
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "entry_count": len(cards),
            "star_dist": {str(k): v for k, v in sorted(dist.items())},
            "quality_notes": QUALITY_NOTE,
        },
        "cards": cards,
    }


# ---------- 羁绊断点表 ----------


def build_traits_json() -> dict:
    raw = json.loads((SRC / "api_trait.json").read_text(encoding="utf-8"))
    data = raw["data"]
    traits: list[dict] = []
    for tft_id, t in sorted(data.items(), key=lambda kv: int(kv[0])):
        num_list = [int(x) for x in str(t.get("num_list") or "").split("|") if x.strip().isdigit()]
        members = [
            {"id": m.get("id"), "name": m.get("name"), "price": m.get("price")}
            for m in (t.get("members") or [])
        ]
        traits.append(
            {
                "id": str(tft_id),
                "name": t.get("name"),
                "type": t.get("type"),
                "max_level": t.get("max_level"),
                "num_list": num_list,
                "effect_desc": (t.get("effect_desc") or "").split("\u4e0a")[0] or t.get("desc"),
                "members": members,
            }
        )
    return {
        "meta": {
            "patch": "18.6",
            "source": "jinchanchan.fun/api/jinchanchan/data?dataType=trait",
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "entry_count": len(traits),
        },
        "traits": traits,
    }


def main() -> None:
    cards_doc = build_cards_json()
    out1 = ROOT / "data" / "cards" / "cards_18.6.json"
    out1.parent.mkdir(parents=True, exist_ok=True)
    out1.write_text(json.dumps(cards_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("cards:", cards_doc["meta"]["entry_count"], cards_doc["meta"]["star_dist"], "->", out1.name)

    traits_doc = build_traits_json()
    out2 = ROOT / "data" / "traits" / "traits_18.6.json"
    out2.parent.mkdir(parents=True, exist_ok=True)
    out2.write_text(json.dumps(traits_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    n_eff = sum(1 for t in traits_doc["traits"] if t["effect_desc"])
    print("traits:", traits_doc["meta"]["entry_count"], f"(effect_desc 非空 {n_eff})", "->", out2.name)


if __name__ == "__main__":
    main()
