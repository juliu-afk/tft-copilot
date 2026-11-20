"""运营策略模块（M6 补课）：阶段化运营建议 + 开局卡组预案 + 任务提示.

v1 教训（2026-11-20 用户实测反馈）：数字读错 + 没有任何策略输出。
本模块基于读数（gold/hp/layer/level/stage）产出可执行的运营提示，
不依赖 8 家面板（那是 M6 后续），先让副官「说话」。

提示类型：
- 经济线：金币 50 之上吃利息，攒钱/花线的分界提示
- 升级线：等级节奏（几级该攒钱上人口）
- 保血线：血量阈值警示
- 层数线：跑刀核心目标（里程碑前的最后冲刺提示）
- 阶段策略：开局/中期/成型的通用打法一句话
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
    # 节奏参考：4-1 前上 5，5-2 前上 6，后期 7/8 择机
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
    return out
