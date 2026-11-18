# TFT Copilot（跑刀副官）

> 金铲铲之战「大橘大利」模式本地只读辅助工具 · 工程主仓
>
> 版本：v0.1.0（仓库初始化） | 游戏版本基线：金铲铲 18.6（2025.11.04）
>
> **机器补记忆，人补导航。** 纯本地、纯只读、零 LLM 运行时。

## ⚠️ 合规声明（必读）

本工具是**只读屏幕提醒器**，不是外挂：

- **零输入模拟** —— 不模拟任何鼠标键盘操作，不代点、不代拖、不代 D 牌
- **零进程读取** —— 不读游戏内存/句柄/网络包，感知边界永远停留在“截屏像素”
- **零联网外传** —— 所有计算在本机完成，数据不出本地 SQLite
- 人机分工：所有需要“导航”的操作（按 Tab 轮播对手、按 E 查玩家列表）由人完成，工具是被动的“记录员”

详见 [docs/design.md](docs/design.md) 第 10 章“安全与合规红线”。**Contributor 同样必须遵守这三条红线。**

## 项目简介

在玩家正常游玩金铲铲 PC 版「大橘大利」模式时，把屏幕上出现过的公开信息截屏、识别、记录、推演，在关键时刻提醒玩家不要漏掉关键操作：

- **层数进度** —— 里程碑预警、速度健康度、达标即停
- **战力评分** —— 全场 8 家战力打分与趋势
- **对位预测** —— 三档胜率区间 + 下家棋盘常预览
- **影响推演** —— 任务 × 层数 × 血量 × 名次四路交叉提醒
- **卡组参谋** —— 局前 200+ 时间卡片组合推演，5 秒出 Top 5

## 快速开始（开发环境）

```bash
# Python 3.13+，uv 包管理
uv sync            # 安装依赖（mss / opencv-python / paddleocr / PyQt6 等）
uv run pytest -q   # 单元测试

# 运行（M1 里程碑后可用）
uv run python -m tft_copilot
```

## 文档

| 文档 | 内容 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 开发流程铁律：四阶段门禁、回溯链、红线代码禁令 |
| [docs/design.md](docs/design.md) | 工程方案 v1.1（15 章详案：架构/感知/决策/引擎/路线图） |
| [docs/roadmap.md](docs/roadmap.md) | 开发路线图与里程碑追踪 |

## 项目结构（规划）

```
tft-copilot/
├── tft_copilot/            # 主包
│   ├── perception/         # 感知层：截屏、模板匹配、OCR、场景调度
│   ├── knowledge/          # 知识层：数值库/模板库/对局库 三腿
│   ├── decision/           # 决策层：四模块规则引擎
│   ├── overlay/            # 交互层：HUD + Toast
│   └── replay/             # 复盘回放 CLI
├── data/
│   ├── rules/              # 攻略 JSON（版本化：rules_v18.6.json）
│   ├── templates/v18.6/    # 识别模板（按游戏版本分目录）
│   └── db/                 # SQLite 对局库
├── tools/                  # 开发期脚本（掌盟爬取、LLM 结构化）
/ docs/                     # 设计文档
└── tests/                  # pytest（unit / integration / regression）
```

## 开发流程

采用四阶段门禁开发（需求 → 方案 → 实现+审查 → 测试门禁），贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

MIT License — 详见 [LICENSE](LICENSE)。
