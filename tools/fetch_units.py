#!/usr/bin/env python3
"""M1-2 开发期爬取脚本：jinchanchan.fun 大橘大利弈子数值库.

白名单目录：本脚本可联网（requests），主包 tft_copilot/ 零网络 import（semgrep 红线）。
数据流：列表页 → 条目索引 → 逐详情页 → raw_html 快照 → 解析 → units_18.6.json。
限速 1req/s，UA 研究标识，403/429 立即停。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE = "https://jinchanchan.fun"
UA = "tft-copilot-research/0.1 (personal study; github.com/juliu-afk/tft-copilot)"
RATE_LIMIT_S = 1.0
RETRY = 3
BACKOFF_S = 2.0

# ---------- HTTP ----------


def http_get(url: str) -> requests.Response:
    """带重试的 GET；4xx 状态码视为站方拒绝，抛 SystemExit 终止整批（PRD 风险条款）。"""
    last_exc: Exception | None = None
    for attempt in range(1, RETRY + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if resp.status_code in (403, 429):
                print(f"[ABORT] {url} -> HTTP {resp.status_code}（站方拒绝，整批终止）")
                sys.exit(2)
            if resp.status_code == 200:
                return resp
            last_exc = RuntimeError(f"HTTP {resp.status_code}")
        except requests.RequestException as exc:  # 网络抖动
            last_exc = exc
        print(f"  retry {attempt}/{RETRY}: {url} ({last_exc})")
        time.sleep(BACKOFF_S)
    raise RuntimeError(f"重试耗尽: {url} ({last_exc})")


# ---------- 列表页 ----------


@dataclass
class IndexEntry:
    hero_id: str
    name: str
    cost: int
    traits: list[str]
    detail_url: str
    portrait_url: str | None = None


def parse_list_page(html: str) -> list[IndexEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[IndexEntry] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='/hero/']"):
        href = a.get("href", "")
        if "_S" not in href:  # 只取当前模式详情链接，跳过模式切换入口
            continue
        hero_id = href.rstrip("/").split("/")[-1]
        if not hero_id.isdigit() or hero_id in seen:
            continue
        seen.add(hero_id)
        text = a.get_text(" ", strip=True)
        entries.append(
            IndexEntry(
                hero_id=hero_id,
                name=_extract_name(text),
                cost=_guess_cost(hero_id),
                traits=[],
                detail_url=href if href.startswith("http") else BASE + href,
            )
        )
    return entries


def _extract_name(text: str) -> str:
    """卡片文本形如 '佛耶戈 1费 暗影岛/迅击战士'，名称取首段。"""
    return text.split()[0] if text.split() else text[:6]


def _guess_cost(hero_id: str) -> int:
    # ID 前两位编码费用档：11xxx->1 ... 15xxx->5（122 条实测全对齐）
    return int(hero_id[:2]) - 10


# ---------- 详情页 ----------


def _txt(node) -> str:  # noqa: ANN001 - bs4 Tag
    return node.get_text(" ", strip=True) if node else ""


def _to_int(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _to_float(text: str) -> float | None:
    cleaned = text.replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_detail_page(html: str, entry: IndexEntry) -> dict[str, Any]:
    """状态机解析：按文本行关键词定位（实测页面结构，样本 11400）。

    布局：名称/费用/羁绊们 → 基础属性(攻速/射程/法力值) → 技能名/类型/描述/数值行
    → 星级成长表：N/星/hp/ad/ar/'/'/mr/crit/'%' 逐行散列。
    注：chr(10) 即换行符，用于规避模板转义。
    """
    soup = BeautifulSoup(html, "html.parser")
    NL = chr(10)
    unit: dict[str, Any] = {
        "id": entry.hero_id,
        "name": entry.name,
        "alias": [],
        "cost": entry.cost,
        "traits": [],
        "attack_speed": None,
        "range": None,
        "mana_start": None,
        "mana_max": None,
        "crit": None,
        "stars": [],
        "skill": {"name": None, "type": None, "detail": None, "scales": []},
        "unlock": {"is_unlockable": False, "condition": None, "price": None},
        "quality_flags": [],
    }

    img = soup.select_one("img[src*='game.gtimg.cn']")
    if img:
        src = img.get("src", "")
        unit["portrait"] = src
        entry.portrait_url = src

    lines = [ln.strip() for ln in soup.get_text(NL, strip=True).split(NL) if ln.strip()]

    # 羁绊：费用数字行 与 "基础属性" 之间的文本行
    for i, ln in enumerate(lines):
        if ln == "基础属性":
            for j in range(i - 1, 0, -1):
                if lines[j].isdigit() and len(lines[j]) <= 2:  # 费用 1-5
                    unit["traits"] = [x for x in lines[j + 1 : i] if x and not x.isdigit()]
                    break
            break

    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln == "攻击速度" and i + 1 < n:
            unit["attack_speed"] = _to_float(lines[i + 1])
            i += 2
            continue
        if ln == "攻击距离" and i + 1 < n:
            unit["range"] = _to_int(lines[i + 1])
            i += 2
            continue
        if ln == "法力值" and i + 3 < n and lines[i + 2] == "/":
            unit["mana_start"], unit["mana_max"] = _to_int(lines[i + 1]), _to_int(lines[i + 3])
            i += 4
            continue
        if ln.endswith("Skill") and i + 2 < n:  # Active Skill / Passive Skill
            if i >= 1:
                unit["skill"]["name"] = lines[i - 1]
            unit["skill"]["type"] = ln.split()[0].lower()
            unit["skill"]["detail"] = lines[i + 1][:400]
            scales_line = lines[i + 2] if i + 2 < n else ""
            unit["skill"]["scales"] = [scales_line] if "|" in scales_line else []
            i += 3
            continue
        # 星级行锚点：数字 + 下一行是 "星"
        if ln.isdigit() and i + 8 < n and lines[i + 1] == "星":
            try:
                row = {
                    "star": int(ln),
                    "hp": int(lines[i + 2]),
                    "ad": int(lines[i + 3]),
                    "ar": int(lines[i + 4]),
                    "mr": int(lines[i + 6]),  # i+5 是 "/"
                    "crit": _to_float(lines[i + 7]) if lines[i + 7].isdigit() else None,
                }
                if unit["crit"] is None and row["crit"] is not None:
                    unit["crit"] = row["crit"]
                unit["stars"].append(row)
                i += 9 if i + 8 < n and lines[i + 8] == "%" else 8
                continue
            except (ValueError, IndexError):
                pass
        i += 1

    # crit 百分数归一（25% -> 0.25）
    if unit["crit"] is not None and unit["crit"] > 1:
        unit["crit"] = unit["crit"] / 100.0
    for row in unit["stars"]:
        if row["crit"] is not None and row["crit"] > 1:
            row["crit"] = row["crit"] / 100.0

    if not unit["skill"]["scales"]:
        unit["quality_flags"].append("missing_skill_scale")

    for a, b in zip(unit["stars"], unit["stars"][1:], strict=False):
        if a["hp"] == b["hp"] and a["ad"] == b["ad"]:
            unit["quality_flags"].append("duplicate_star_rows")
            break

    return unit


def find_redundant(units: list[dict[str, Any]]) -> list[list[str]]:
    pairs: list[list[str]] = []
    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            a, b = units[i], units[j]
            if a["name"] == b["name"] and a["cost"] == b["cost"] and set(a["traits"]) == set(b["traits"]):
                pairs.append([a["id"], b["id"]])
    return pairs


# ---------- 主流程 ----------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode-code", default="16_18.18.1_S400001")
    ap.add_argument("--out", default="data/units")
    ap.add_argument("--raw-dir", default="data/units/raw_html")
    ap.add_argument("--templates", default="data/templates/v18.6/portraits")
    ap.add_argument("--patch", default="18.6")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl_dir = Path(args.templates)
    tpl_dir.mkdir(parents=True, exist_ok=True)

    list_url = f"{BASE}/hero"  # 列表页默认当前模式（大橘大利）
    list_cache = raw_dir / "_list.html"
    print(f"[1/4] 拉取列表页 {list_url}")
    if list_cache.exists() and list_cache.stat().st_size > 10_000:
        resp_text = list_cache.read_text(encoding="utf-8")
        print("  （复用磁盘缓存的列表页）")
    else:
        resp = http_get(list_url)
        resp_text = resp.text
        list_cache.write_text(resp_text, encoding="utf-8")
    entries = parse_list_page(resp_text)
    print(f"  条目索引 {len(entries)} 个")

    units: list[dict[str, Any]] = []
    failed: list[str] = []
    reused = 0
    for idx, entry in enumerate(entries, 1):
        raw_file = raw_dir / f"{entry.hero_id}.html"
        try:
            if raw_file.exists() and raw_file.stat().st_size > 10_000:  # 断点续采：磁盘快照直接复用
                reused += 1
                html_text = raw_file.read_text(encoding="utf-8")
            else:
                time.sleep(RATE_LIMIT_S)
                detail = http_get(entry.detail_url)
                raw_file.write_text(detail.text, encoding="utf-8")
                html_text = detail.text
            units.append(parse_detail_page(html_text, entry))
            if idx % 20 == 0 or idx == len(entries):
                print(f"  [{idx}/{len(entries)}] ✓ {entry.name}({entry.hero_id})")
        except Exception as exc:  # noqa: BLE001 - 单页失败不阻塞
            failed.append(entry.hero_id)
            print(f"  [FAIL] {entry.hero_id}: {exc}")
    print(f"[2/4] 解析完成：{len(units)} 成功 / {len(failed)} 失败 / 复用磁盘快照 {reused} 页")

    # 头像下载（失败不阻塞）
    missing: list[str] = []
    print(f"[3/4] 下载头像至 {tpl_dir}")
    for u in units:
        url = u.get("portrait")
        if not url:
            missing.append(u["id"])
            continue
        dest = tpl_dir / f"{u['id']}.png"
        if dest.exists():
            continue
        try:
            time.sleep(RATE_LIMIT_S)
            r = http_get(url)
            dest.write_bytes(r.content)
        except Exception:  # noqa: BLE001
            missing.append(u["id"])
    print(f"  头像 {len(units) - len(missing)} 下载 / {len(missing)} 缺失")

    redundant = find_redundant(units)
    payload = {
        "schema_version": 2,
        "meta": {
            "patch": args.patch,
            "source_page_version": args.mode_code.split("_")[1],
            "mode_code": args.mode_code,
            "source": "jinchanchan.fun",
            "fetched_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            "entry_count": len(units),
        },
        "redundant_ids": redundant,
        "units": units,
    }
    out_file = out_dir / f"units_{args.patch}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[4/4] 写出 {out_file} | 条目 {len(units)} | 重复对 {len(redundant)} | 失败 {len(failed)}")

    flags_stat: dict[str, int] = {}
    for u in units:
        for f_ in u["quality_flags"]:
            flags_stat[f_] = flags_stat.get(f_, 0) + 1
    print(f"  quality_flags 统计: {flags_stat or '无'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
