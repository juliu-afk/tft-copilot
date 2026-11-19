# 阶段1-PRD：M5 L1.5 对位引擎（属性对比 + 装备查表 + 站位粗算）

> 版本：v1.0 | 日期：2026-11-19 | 基线：工程方案 v1.1 §5.3 / §6.1-6.2 | roadmap M5 行
>
> 上一里程碑：M4 卡组参谋已合入（83ea241，148 测试）。本 PRD 将 L0 查表法（sigmoid 差值）升级为 L1.5 属性对比引擎。

## 1. 背景与用户问题

M3 决策层的对位预测模块目前是 L0：`predict(my_power, opp_power)` 只吃两个战力总分（星级+羁绊+趋势的加权），sigmoid k=0.08 映射成胜率。三个已知短板：

1. **装备盲区**：power_score 的 item 分量恒 0（M3 遗留，注释已标注「装备识别 M5」）。无尽之刃和空装在 L0 眼里没区别。
2. **面板没有装配**：羁绊分只数激活数（sum(min(count,6))*1.5 近似），双方 20 层数的和 4 层数的斗士在 L0 眼里一样强。
3. **站位零感知**：前 4 后 6 还是全员沉底，L0 不看。实战中同一阵容站位好坏能差一档胜负。

用户问题（用户故事）：

- **US1**：作为一名连败流玩家，对位面板弹出时，我想看到「双方结算面板对比 + 胜率三档」而不是一个裸总分差，以便判断这局该不该故意输。
- **US2**：作为一名运营型玩家，我想在 HUD 上看到对手主 C 的成装数量与档位（成装/光明/神器），以便提前补坦度或追质量。
- **US3**：作为一名复盘玩家，我想在赛后用 `replay --match N` 看每场对位的四象限归因（高置信×对/错），以便知道引擎哪类局判不准。

优先级：US1 = P0（L1.5 核心）；US2 = P0（装备查表是 L1.5 输入）；US3 = P1（四象限统计在 M3 store 已有落库字段，本迭代补齐归因查询 CLI）。

## 2. 范围

### In Scope（三件套）

1. **装备数值库**（equips_18.6.json）：从已抓取的 api_equip.json（204 件，含合成路径 synthesis1/2）提炼 L1.5 所需 schema：id/name/type（基础/成装/光明/神器/特殊/纹章）/grade 权重/desc。加载器三重校验沿用 M1-M4 铁律。
2. **L1.5 属性对比引擎**（tft_copilot/decision/panel.py + matchup15.py）：
   - `PanelEngine.assemble(state)`：给一家 PlayerState 装配结算面板——套羁绊加成近似（断点表 effect_desc 解析出的 hp/ad 增益）+ 装备增益近似（类别权重）→ 输出 DPS/EHP/爆发三轴。
   - `predict_l15(my_panel, opp_panel, positions)`：三轴加权差 → 胜率区间 + 三档 + 置信度。缺数据自动降级 L0（现有 sigmoid 链路保底）。
3. **站位粗算**（tft_copilot/decision/positioning.py）：基于 range 分层（range 1=近战/前排，range≥4=远程/后排）+ 前后 4×2 格位启发式，输出站位档位（standard/aggressive/defensive）与增益系数，进 predict_l15 的修正项。

### Out of Scope（Non-Goals）

- L1.75 主 C 精细仿真（技能循环、tick 循环、Monte Carlo）——升级触发器未达成（SQLite 未攒 500 局）
- 装备图标模板识别（感知层范畴，M6 真机联调时补）
- 强化符文（hex）数值装配——297 条 hex 的 description 全是自由文本，结构化成本高，留 M6+ 按需启用
- 血量趋势分 trend 的重估——仍用 M3 实现，M6 回归校准
- 四象限查询 CLI 之外的复盘 UI

## 3. 验收标准

### AC1 装备库与加载器（P0）

- AC1.1 equips_18.6.json 覆盖 api_equip.json 全部 204 件装备，无遗漏、无重名。
- AC1.2 三重校验：文件名版本 == meta.patch == 数据规模一致；id 连续无跳号。
- AC1.3 `equips-check` CLI：加载即校验，输出件数/类型分布/校验结果，非 0 退出码表示失败。
- AC1.4 grade 权重表（成装 1.0 / 光明 1.6 / 神器 2.5，特殊 0.3 / 纹章 0.8）有 WHY 注释且可配置（模块级常量，非散落魔法数）。

### AC2 L1.5 引擎（P0）

- AC2.1 `PanelEngine.assemble` 输出 PanelScores（dps/ehp/burst 三轴，0-100 归一），空板凳（units=None）返回 None，不猜。
- AC2.2 羁绊装配近似：激活断点数 > 激活数近似（M3 的 sum(min(count,6))*1.5）——至少区分「斗士(4)」和「斗士(2)」两档强度。使用 M4 traits 断点表 num_list。
- AC2.3 `predict_l15` 输出三档胜率（high/even/low）+ 置信度（high/mid/low），档位阈值沿用 L0（0.65/0.35），保持决策层接口一致性。
- AC2.4 降级链完整：任一侧 panel 为 None → 回退 predict()（L0）→ 输出标记 `engine="L0"`；两侧齐 → `engine="L1.5"`。
- AC2.5 性能预算：单次 predict_l15（含双方面板装配）≤50ms（合成局口径，122 弈子库全量查表）。

### AC3 站位粗算（P1）

- AC3.1 range 分层覆盖率 100%（range 1 / range 2 / range≥4 三档，122 弈子全库可分）。
- AC3.2 站位档位判定：前排占比 ≥60% → aggressive，≤30% → defensive，其余 standard。
- AC3.3 站位修正系数进 predict_l15：远程主 C 受威胁（对方近战多且我方后排暴露）扣 0-5 分面板分。

### AC4 四象限归因查询（P1）

- AC4.1 `replay quadrant --match N`（或 engine 查询函数）输出四象限计数与高置信判错率。
- AC4.2 高置信×错率口径与设计文档 §5.3 一致：仅统计 confidence=high 的预测，判错率 = 高置信错 / (高置信对 + 高置信错)。
- AC4.3 判错率 ≤15% 为验收线（合成局口径；真机 200 帧口径移交 M6）。

### AC5 工程门禁（P0）

- AC5.1 全量测试通过，新增测试 ≥25 用例。
- AC5.2 semgrep 红线扫描 0 致命。
- AC5.3 ruff 0 违规。
- AC5.4 新模块头部注释含 budget 与红线自查声明（沿用 M2-M4 格式）模块注释风格。
- AC5.5 power_score 的 item 分量从恒 0 改为读取 PlayerState.items（装备快照），无 items 字段时保持 0（降级不炸）。

## 4. 待确认问题（默认方案）

| # | 问题 | 默认方案（不回复则按此执行） |
|---|---|---|
| Q1 | 装备库要不要带中文 desc？ | 带。体积可控（204 件 ×~80 字符），人工校验与后续 LLM 提炼都需要 |
| Q2 | 站位粗算要不要输出建议文案（Advice）？ | 本迭代只输出档位+系数进面板，建议文案 M6 联调时按真机效果补 |
| Q3 | 四象限查询放 replay CLI 还是新 CLI？ | 放 replay CLI 子命令（replay quadrant），不新增顶层命令 |

## 5. 红线自查

- 零输入模拟：无。纯数值计算。
- 零进程读取：无。
- 颐联网外传：主包零网络。api_equip.json → equips_18.6.json 的提炼在 tools/ 脚本完成（离线一次性）。
- 装备数据源为 jinchanchan.fun 公开 API（M4 已抓取快照），无版权风险增量（同 M4 口径）。

## 6. 验收口径声明

本 PRD 全部 AC 的「合成局口径」指：测试构造 PlayerState/UnitOnBoard/ItemOnBoard，直接调引擎函数，不起进程、不截屏。真机 200 帧校准是 M6 范畴。判错率 ≤15% 在合成局以「构造已知强弱的阵容对」验证方向正确性（强阵容胜率显著高于弱阵容，四象限不出现高置信×错占多数）。
