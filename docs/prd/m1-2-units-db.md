# PRD：M1-2 弈子数值库（大橘大利 18.6）

- 版本：v1.0（2026-11-18）
- 状态：已批准（承接 M1-2 调研结论）
- 上游：docs/design.md §5 数据三腿之「静态数值库」
- 数据源：jinchanchan.fun（大橘大利模式页，SSR 渲染，官方图床 game.gtimg.cn，站方标注 AI Ready）

## 1. 背景与目标

M1-1 已完成攻略规则 JSON 化（38 任务/20 奖励档）。M1-2 目标：把大橘大利模式全量弈子数值结构化为 `data/units/units_18.6.json`，为 M2 感知层（模板匹配）与 M3 决策层（战力评分）提供数值地基。

### 调研结论（2026-11-18 实测）

| 通道 | 判定 |
|---|---|
| jinchanchan.fun 大橘大利页 | ✅ **主通道**：SSR 全量数值（122 条目：攻速/射程/法力/暴击/星级成长/技能/羁绊成员），详情页 URL 规律 `/{hero_id}`，官方图床，AI Ready |
| CDragon（static/raw） | ❌ static 域被墙（HTTP 000），raw 无 TFT set 路径 |
| datatft.com | ❌ SPA 无公开端点，JS 内无数据 URL |
| 掌盟 H5 / jcc.qq.com | ❌ 客户端渲染，普通 requests 不可达 |
| 版本口径 | ⚠️ 站点模式页版本 18.18.1 ≠ 官方公告版本号 18.6——以官方公告口径为准，站点模式码仅作抓取坐标 |
| 星级档数 | ⚍ 大橘大利有升星机制（1-4 费 3 档，5 费 4 档；页面展示 6 行含重复），解析保留原始行 + quality_flags 标注 |

## 2. 范围

### 做

- 122 条目全量抓取（含重复条目，如兰博×2、杰斯×2——不同羁绊版本独立 ID）
- 字段：id/name/cost/traits[]/as/range/mana_start/mana_max/crit/stars[](hp/ad/ar/mr/crit)/skill{name,type,desc,scales}/unlock
- 三重版本校验（与 M1-1 同构）：文件名版本 ↔ meta.patch ↔ schema_version
- 顶层 `redundant_ids` 数组记录已知重复条目对（示例：`[["11410","11411"]]` 表示两个兰博条目互为重复），供去重判定用
- `tools/fetch_units.py` 开发期爬取脚本（白名单目录，可联网，永远不进运行时）
- `python -m tft_copilot units-check` CLI 统计校验
- 中文数字字段规范：数值一律存数字（hp/ad/ar/mr 为 int，as/crit 为 float），描述文本原样保留
- 单元测试 ≥15 用例

### 判重规则

两条目若 name 相同、cost 相同且 traits 集合等价（顺序无关），判为重复对，记入 redundant_ids。traits 不完全一致时（如兰博不同羁绊版本）不判重，视为独立条目。

### 数据质量口径

- 技能数值 3 档 vs 星级 6 行不对应：skill.scales 原样存站点档位数，quality_flags 加 `skill_scale_mismatch`
- 站点相邻星级行数值相同（如 2 星=3 星）：quality_flags 加 `duplicate_star_rows`
- quality_flags 枚举：duplicate_star_rows / skill_scale_mismatch / missing_skill_scale / manual_fix
- 数值准确性抽检：主通道抓完后，随机抽 5-8 个弈子与官方公告/掌盟截图对答案，偏差 >1% 则记 manual_fix 并修数据

### 不做

- 装备数值库、装备合成树、海克斯数据（M2 再做，需先验证页面同构性）
- 游戏内实测验证数值准确性（留 M4 数据闭环，靠对局快照反校）
- 星级档归一化（保留原始行 + flags；升星档位机制未经官方文档确认，主观归一化风险大于收益，M4 有实测数据后重审）
- 自动追更（每版本重跑 fetch + 人工抽检 ≤30min，维持既有结论）
- 模板图片真实性校验（fetch 顺带下载头像至 data/templates/v18.6/，校验留 M2）

## 3. 验收标准

- [ ] AC1：`python -m tft_copilot units-check` 打印 122 条目 / 费用分布 / trait 覆盖统计，无校验错误
- [ ] AC2：加载器三重校验（文件名 18.6 ↔ meta.patch=18.6 ↔ schema_version=2）通过
- [ ] AC3：任一星级行缺 hp/ad/ar/mr/crit 五维之一 → 校验失败；stars 保留原始档位行数，不要求固定行数
- [ ] AC4：tools/ 脚本零网络 import 进主包（semgrep 校验，白名单目录除外）
- [ ] AC5：fetch_units.py 完整 122 页循环一次跑通，失败页自动重试 3 次（退避 2s），最终成功率 ≥95%（目标 100%）
- [ ] AC6：单测 ≥15 用例全绿，覆盖加载/校验/查询/去重四组
- [ ] AC7：单文件 <2MB（122 条目全字段预计 300-500KB，余量充足）

## 4. 风险与应对

| 风险 | 应对 |
|---|---|
| 站点改版/失联 | data/units/raw_html/ 落盘原始 HTML 快照，本地可恢复解析 |
| 数值与游戏内实况不符 | 三源对答案（公告+掌盟截图+站点），偏差进 quality_flags |
| 站方态度/robots 变化 | 限速 1req/s、带 UA、403/429 即停；数据仅供个人研究 |
| 版本口径漂移（18.18.1 vs 18.6） | meta 同时记 source_page_version 与 patch；两口径差 >1 时 fetch 警告人工确认 |
| 星级档数不明 | 保留原始行 + quality_flags，M4 实测反校后重审 |

## 5. 里程碑挂接

M1「数据就绪」第 2/3 块。完成后 roadmap M1 状态更新为 3/3（M1-3 掌盟爬取已被本次调研替换为 jinchanchan 通道），里程碑整体放行。
