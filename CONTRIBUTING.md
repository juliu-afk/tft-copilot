# 贡献指南

## ⚠️ 前置必读：三条红线

本项目是**只读屏幕提醒器**，不是外挂。任何 PR 触碰以下红线直接拒绝：

1. **零输入模拟** —— 禁止引入 pyautogui / pynput / SendInput / mouse_event 等任何输入模拟 API
2. **零进程读取** —— 禁止 ReadProcessMemory / OpenProcess / win32api / 抓包库
3. **零联网外传** —— 运行时主包（`tft_copilot/`）零网络请求；`tools/` 开发期脚本除外

CI 每次 PR 自动执行 semgrep 红线扫描（`.semgrep/redlines.yaml`），违规即红灯。

## 开发流程（四阶段门禁）

1. **阶段1 PRD** → 需求澄清、用户故事、验收标准（保存至 `docs/requirements/YYYY-MM-DD-*/`）
2. **阶段2 技术方案** → 模块设计、数据流、与 PRD 对照表
3. **阶段3 编码+3b审查** → feature 分支开发，semgrep 红线扫描 + lint + 测试
4. **阶段4 测试门禁** → PR CI 全绿 + 审查通过后方可合并

详细规则见 [CLAUDE.md](CLAUDE.md)。

## PR 规范

- Conventional Commits：`feat(module): 描述`，subject ≤50 字符
- 禁止直接 push main，一律 PR
- 禁止 force push
- 感知层改动必须附离线回放测试（录屏帧 fixtures）

## 版本化铁律

- 知识库 JSON 文件名必须带游戏版本：`rules_v18.6.json`
- 对局库每行带 `version` 列，版本不匹配拒绝入库
- 模板库按版本目录：`templates/v18.6/`

## 行为准则

理性讨论，对事不对人。识别/决策规则的误判欢迎提 issue，附截图与游戏版本号。
