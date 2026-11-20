# -*- coding: utf-8 -*-
"""选秀/强化符文选前推荐（M6.5，2026-11-20）.

触发时机：live 检测到画面顶部/中央出现「选秀」「强化符文」关键词（OCR 全帧词）。
推荐原则（大橘大利 18.6 实用向）：
- 选秀装备优先级：成型装 > 主C适配基础装 > 万金油基础装
- 符文三选一：彩>金>银（同档看经济/战力标签），跑刀模式经济符文优先

红线自查：零网络、零输入模拟、零进程读取，纯查表。
"""
from __future__ import annotations

from tft_copilot.decision.snapshot import Advice


# ---------- 选秀装备优先级 ----------

# 万金油成型装（拿到不亏）
DRAFT_EQUIP_PRIORITY: list[tuple[str, str]] = [
    ("无尽之刃", "物理C通用，暴击体系核心"),
    ("海克斯科技枪刃", "全能型：伤害+治疗"),
    ("朔极之矛", "技能C通用启动装"),
    ("最后的轻语", "破甲，物理队通用"),
    ("大天使之杖", "法系C通用，成长型"),
]

# 基础装优先级（前几轮选秀多是散件）
BASIC_EQUIP_PRIORITY: list[tuple[str, str]] = [
    ("暴风之剑", "物理C核心散件，万金油"),
    ("反曲之弓", "攻速体系+多种合成路线"),
    ("无用大棒", "法系核心散件"),
    ("巨人腰带", "肉装通用，前排缺就拿"),
]


def draft_guide(round_no: int, gold: int | None = None) -> list[Advice]:
    """选秀前提示：按轮次给装备优先级。前 3 轮散件为主，之后成型装。"""
    out: list[Advice] = []
    if round_no <= 3:
        picks = BASIC_EQUIP_PRIORITY
        head = "选秀（前几轮散件为主）"
    else:
        picks = DRAFT_EQUIP_PRIORITY
        head = "选秀（成型装优先）"
    lines = "；".join(f"{n}（{why}）" for n, why in picks[:3])
    out.append(Advice("info", f"{head}：优先 {lines}", "draft"))
    return out


# ---------- 强化符文三选一 ----------

TIER_ORDER = {"独特": 0, "彩": 1, "金": 2, "银": 3}

# 跑刀模式经济优先的高分符文（名字 -> 一句话理由）
ECON_HEXES: list[tuple[str, str]] = [
    ("对冲基金", "利息上限10，跑刀经济天花板"),
    ("小额奖金 I", "每回合稳定额外收入"),
    ("存心失利", "连败流配合：输=钱+刷新"),
    ("升级咯！", "省下的买牌钱都是利息"),
]


def hex_guide(hexes_book, round_no: int, gold: int | None = None) -> list[Advice]:
    """强化符文选前提示：三档选择原则 + 当前局面推荐。

    hexes_book: HexesBook（None 时只给原则不给具体名）。
    """
    out: list[Advice] = []
    out.append(Advice(
        "info",
        "符文三选一原则：彩>金>银；跑刀优先经济（每回合多金=多几层），"
        "战力符文只在连败断不了时拿",
        "hex",
    ))
    if hexes_book is not None and hexes_book.count:
        # 从库里捞真实存在的经济符文名（防止推荐表过版本失效）
        recs: list[tuple[str, str, str]] = []
        for name, why in ECON_HEXES:
            h = hexes_book.find(name)
            if h is not None:
                recs.append((name, h.tier, why))
        if recs:
            lines = "；".join(f"{n}（{t}档·{why}）" for n, t, why in recs[:3])
            out.append(Advice("info", f"经济优先看：{lines}", "hex"))
    return out


def pick_event_advices(event: str, hexes_book, round_no: int, gold: int | None = None) -> list[Advice]:
    """事件分发入口：live 检测到关键词后调用。event: 'draft' | 'hex'。"""
    if event == "draft":
        return draft_guide(round_no, gold)
    if event == "hex":
        return hex_guide(hexes_book, round_no, gold)
    return []
