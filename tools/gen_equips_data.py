"""M5 装备库生成脚本：api_equip.json 快照 -> equips_18.6.json（离线一次性）。

输入：data/pending_templates_test/api_equip.json（M4 抓取的 jinchanchan.fun 快照）
输出：data/equips/equips_18.6.json（204 件，含 grade 权重与合成路径）

开发期脚本（tools/ 白名单），主包运行时零网络。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "pending_templates_test" / "api_equip.json"
DST = ROOT / "data" / "equips" / "equips_18.6.json"
PATCH = "18.6"
VERSION_ID = "16_18.18.1_S400001"

# 类型 -> grade 权重（power_score item 分量锚点）
# WHY: 以「同等价值成装=1.0」锚定：光明≈成装x1.6（掌盟常规溢价），神器独立掉落强度最高；
# 纹章不加数值只扩羁绊入口按 0.8；特殊装备多为组件/消耗品 0.3；基础散件最弱 0.25。
# 设计初值，M6 与战力权重同批回归重估。
GRADE_BY_TYPE = {
    "成型装备": 1.0,
    "光明武器": 1.6,
    "神器装备": 2.5,
    "转职纹章": 0.8,
    "特殊装备": 0.3,
    "基础装备": 0.25,
}


def main() -> None:
    raw = json.loads(SRC.read_text(encoding="utf-8"))["data"]
    equips = []
    for it in raw.values():
        etype = it.get("type") or ""
        if etype not in GRADE_BY_TYPE:
            raise SystemExit(f"未知装备类型: {etype!r} (id={it['id']})")
        synth = [s for s in (it.get("synthesis1"), it.get("synthesis2")) if s]
        equips.append(
            {
                "id": it["id"],
                "name": it["name"],
                "type": etype,
                "grade": GRADE_BY_TYPE[etype],
                "synth": synth,
                "desc": it.get("desc") or "",
            }
        )
    equips.sort(key=lambda e: e["id"])
    # 基本校验：id 唯一 + 无重名
    ids = [e["id"] for e in equips]
    names = [e["name"] for e in equips]
    assert len(ids) == len(set(ids)), "id 重复"
    assert len(names) == len(set(names)), "重名"
    out = {
        "schema_version": 2,
        "meta": {
            "patch": PATCH,
            "version_id": VERSION_ID,
            "count": len(equips),
            "source": "jinchanchan.fun equip API",
        },
        "equips": equips,
    }
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # 打印类型分布
    dist: dict[str, int] = {}
    for e in equips:
        dist[e["type"]] = dist.get(e["type"], 0) + 1
    print(f"OK {len(equips)} 件 -> {DST}")
    for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    synth_n = sum(1 for e in equips if e["synth"])
    print(f"  含合成路径: {synth_n}")


if __name__ == "__main__":
    main()
