"""运营策略模块（M6 补课）：阶段化运营建议 + 开局卡组预案 + 连胜连败收入预估.

v1 教训（2026-11-20 用户实测反馈）：数字读错 + 没有任何策略输出。
v3（2026-11-20 下午）：加连胜/连败追踪 + 下回合收入预估（基础5+连X奖励+利息）。

提示类型：
- 经济线：金币 50 之上吃利息，攒钱/花线的分界提示
- 升级线：等级节奏（几级该攒钱上人口）
- 保血线：血量阈值警示
- 层数线：跑刀核心目标（里程碑前的最后冲刺提示）
- 阶段策略：开局/中期/成型的通用打法一句话
- 收入线：连胜/连败 + 下回合收入预估
- 任务线：大橘大利任务（吃利息/升级/连胜等）达成路径

budget: <1ms/次（纯查表）。
红线自查：零网络、零输入模拟、零进程读取。
"""

from __future__ import annotations

from tft_copilot.decision.snapshot import Advice


def economy_advice(gold: int | None, stage_minor: int | None) -> list[Advice]:
    """经济线：利息阈值提示。"""
    if gold is None:
        return []
    out: list[Advice] = []
    if 40 <= gold < 50:
        out.append(Advice(
            "info",
            f"金币 {gold}：再攒 {50 - gold} 到 50 吃满 5 利息，本回合少刷牌",
            "economy",
        ))
    elif gold >= 50:
        out.append(Advice(
            "info",
            f"金币 {gold}：已过 50 线，每回合利息 +{min(gold // 10, 5)}，只花超出部分",
            "economy",
        ))
    return out


def level_advice(level: int | None, stage_major: int | None) -> list[Advice]:
    """升级线：等级节奏参考（大橘大利常见节奏）。"""
    if level is None:
        return []
    out: list[Advice] = []
    if stage_major is not None:
        if stage_major <= 2 and level < 5:
            out.append(Advice(
                "info",
                f"等级 {level}：前期（{stage_major}-x）保持 4-5 级，拿对子攒经济",
                "level",
            ))
        elif stage_major in (3, 4) and level < 7:
            out.append(Advice(
                "info",
                f"等级 {level}：中期该上人口了（目标 7），血量健康可慢，掉血快提速",
                "level",
            ))
        elif stage_major >= 5 and level < 8:
            out.append(Advice(
                "info",
                f"等级 {level}：后期冲 8 找四费卡，等级压制战力质变",
                "level",
            ))
    return out


def hp_advice(hp: int | None) -> list[Advice]:
    """保血线。"""
    if hp is None:
        return []
    out: list[Advice] = []
    if hp <= 30:
        out.append(Advice(
            "warn",
            f"血量 {hp}：进入危险区，全场强牌直接拿，放弃完美主义",
            "hp",
        ))
    elif hp <= 50:
        out.append(Advice(
            "info",
            f"血量 {hp}：过半了，开始拿即时战力卡保血",
            "hp",
        ))
    return out


def layer_advice(layer: int | None, milestones=(10, 25, 50, 100, 200, 300, 400, 500, 625, 1000, 1250)) -> list[Advice]:
    """层数线：跑刀目标冲刺提示（每里程碑一次）。"""
    if layer is None:
        return []
    for n in milestones:
        if n - 3 <= layer < n:
            dist = n - layer
            return [Advice(
                "info",
                f"层数 {layer}：距 {n} 层档还差 {dist} 层，稳住节奏别浪",
                "layer_sprint",
            )]
    return []


def phase_strategy(stage_major: int | None, scene: str) -> list[Advice]:
    """阶段整体策略：开局/中期/成型各一句。"""
    if stage_major is None:
        return []
    text = {
        1: "开局期：只拿体系对子，非体系卡直接卖，经济优先",
        2: "前期：定方向（看来得牌定阵容），开始锁卡攒利息",
        3: "中期：阵容成型关键期，7 级前把核心二星，装备给主 C",
        4: "中后期：该上 8 上 8，补质量牌，装备合成别拖",
        5: "后期：追三星核心或保血争前四，每回合检查对手阵容",
        6: "决赛圈：对位拉满，站位针对最后一两家调整",
    }.get(stage_major)
    if text:
        return [Advice("info", text, "phase")]
    return []


def streak_bonus(n: int) -> int:
    """连X 奖励金（标准 TFT 规则：2-3 连 +1，4 连 +2，5+ 连 +3）。"""
    a = abs(n)
    if a >= 5:
        return 3
    if a == 4:
        return 2
    if a >= 2:
        return 1
    return 0


def next_income(gold: int | None, streak: int) -> int | None:
    """下回合收入预估：基础 5 + 连X奖励 + 利息（10 金 1 息，上限 5）。"""
    inc = 5 + streak_bonus(streak)
    if gold is not None:
        inc += min(gold // 10, 5)
        return inc
    return None


def streak_advice(gold: int | None, streak: int) -> list[Advice]:
    """连胜/连败 + 下回合收入预估。"""
    if streak == 0:
        return []
    label = f"{abs(streak)}连胜" if streak > 0 else f"{abs(streak)}连败"
    sb = streak_bonus(streak)
    parts = ["基础5"]
    if sb:
        parts.append(f"连{abs(streak)}奖励{sb}")
    if gold is not None:
        parts.append(f"利息{min(gold // 10, 5)}")
    total = 5 + sb + (min(gold // 10, 5) if gold is not None else 0)
    return [Advice(
        "info",
        f"{label}：下回合收入 约{'+'.join(parts)}={total} 金",
        "income",
    )]


def opening_plan(deck_plan: tuple[str, ...], round_no: int) -> list[Advice]:
    """开局卡组预案提示（前 2 回合显示一次）。"""
    if deck_plan and round_no <= 2:
        return [Advice(
            "info",
            "开局预案：" + " + ".join(deck_plan) + "（对应卡见到就拿）",
            "deck_plan",
        )]
    return []


def all_strategy_advices(
    nums: dict,
    scene: str,
    round_no: int,
    deck_plan: tuple[str, ...] = (),
    streak: int = 0,
) -> list[Advice]:
    """运营策略总入口：live 每回合调用。"""
    gold = nums.get("gold")
    hp = nums.get("hp")
    layer = nums.get("layer")
    level = nums.get("level")
    smaj = nums.get("stage_major")
    smin = nums.get("stage_minor")
    out: list[Advice] = []
    out += opening_plan(deck_plan, round_no)
    out += phase_strategy(smaj, scene)
    out += economy_advice(gold, smin)
    out += level_advice(level, smaj)
    out += hp_advice(hp)
    out += layer_advice(layer)
    out += streak_advice(gold, streak)
    return out
