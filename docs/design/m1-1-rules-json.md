# 技术方案：M1 迭代 1 —— rules JSON schema 与知识层加载器

| 项 | 值 |
|---|---|
| 迭代 | M1-1 |
| PRD | docs/prd/m1-1-rules-json.md |
| 状态 | 已批准 |
| 日期 | 2026-11-18 |

## 1. 模块归属

`tft_copilot/knowledge/`（五层架构中的知识层）。本迭代交付 3 个文件：

```
tft_copilot/knowledge/
├── __init__.py        # 导出 RulesBundle / load_rules / 异常类
├── rules_loader.py    # 加载 + 三重校验 + 查询接口
└── (schema 定义内嵌于 rules_loader，规模小不值得独立模块)
data/rules/
└── rules_18.6.json    # 知识库数据（版本化命名铁律）
tests/unit/
└── test_rules_loader.py
```

## 2. JSON schema（rules_18.6.json）

```json
{
  "meta": {
    "patch": "18.6",
    "mode": "daju_dali",
    "schema_version": 1,
    "sources": ["官方更新公告18.6", "官方钥匙图鉴", "DataTFT", "7724/川川云/电玩帮"],
    "generated_at": "2026-11-18"
  },
  "tasks": [
    {
      "id": "refresh_shop_easy",
      "name": "刷新商店·简单",
      "category": "economy",
      "tier": "good",
      "tier_note": "全路线顺手做：刷店本来就是运营动作",
      "routes": ["win_streak", "lose_streak", "steady", "blood_for_layers"],
      "variants": [
        {"stage": 2, "requirement": "5次", "layers": 40},
        {"stage": 3, "requirement": "6次", "layers": 40},
        {"stage": 4, "requirement": "8次", "layers": 30},
        {"stage": 5, "requirement": "8次", "layers": 30},
        {"stage": 6, "requirement": "8次", "layers": 30}
      ]
    }
  ],
  "rewards": [
    {
      "layers": 300,
      "options": ["14金+4费×3", "2金+神器锻造器", "12金+成装锻造器+重铸器"],
      "quality": "strong",
      "note": "强度≈金色海克斯；缺战力拿神器，缺经济拿A"
    }
  ],
  "keys": [
    {
      "id": "order_key",
      "name": "秩序钥匙",
      "unlock": "三星奇亚娜 + 完成4个以绪塔尔任务",
      "effects": ["太阳碎片+50%", "携带者击败敌人获得2金币"],
      "strategy": "3阶段解锁，全程经济引擎；三星奇亚娜自戴双吃"
    }
  ],
  "routes": [
    {
      "id": "lose_streak",
      "name": "精致连败流",
      "condition": "开局牌烂、质量低、血量>70",
      "stage_23_tasks": ["lose_3", "unit_death", ...],
      "stage_45_tasks": [...]
    }
  ]
}
```

### 字段规约

| 字段 | 类型 | 约束 |
|---|---|---|
| meta.patch | str | 必须等于文件名中的版本段（三重校验第 1 重） |
| meta.schema_version | int | 加载器支持 =1；>1 抛 SchemaVersionError（第 3 重） |
| tasks[].id | str | 唯一，snake_case，程序引用键 |
| tasks[].category | enum | economy / combat / streak / risk / milestone / bench |
| tasks[].tier | enum | good / warn / bad |
| tasks[].routes | list[str] | 元素必须存在于 routes[].id |
| tasks[].variants | list | 非空；stage ∈ 2..6 且升序；layers > 0 |
| rewards[].layers | int | 升序唯一 |
| rewards[].quality | enum | weak / normal / strong / jackpot |
| rewards[].options | list[str] | 非空（多选一） |
| routes[].stage_23_tasks / stage_45_tasks | list[str] | 元素必须存在于 tasks[].id |

### requirement 字段格式

保留"数字+单位"原样（如 "5次"、"24XP"、"60金"）。不做数值拆分——本迭代查询层不需要数值运算，拆分留给决策模块提出明确需求时再做（避免过度设计）。

## 3. 加载器接口（rules_loader.py）

```python
class RulesValidationError(Exception): ...
class VersionMismatchError(RulesValidationError): ...
class SchemaVersionError(RulesValidationError): ...

class RulesBundle:
    patch: str
    tasks: dict[str, Task]        # by id
    rewards: list[Reward]         # layers 升序
    keys: list[Key]
    routes: dict[str, Route]      # by id

    # 查询接口
    def get_task(self, task_id) -> Task
    def tasks_by_stage_route(self, stage: int, route: str) -> list[Task]   # 路线推荐 ∩ 该阶段有变体，按推荐序
    def tasks_by_tier(self, tier: str, stage: int | None = None) -> list[Task]
    def next_reward(self, current_layers: int) -> Reward | None            # 下一档未达成的奖励
    def reward_at(self, layers: int) -> Reward | None                      # 档位精确查询

def load_rules(patch: str = "18.6", data_dir: Path | None = None) -> RulesBundle
    # data_dir 缺省 = 包内 data/rules/（相对仓库根定位，不依赖 cwd）
    # 三重校验：文件名版本↔meta.patch / 文件存在 / schema_version
```

### 查询语义细节

- `tasks_by_stage_route(4, "lose_streak")`：取该路线推荐序列中在阶段 4 有 variant 的任务，按推荐顺序返回，供决策模块直接生成提醒文案
- `next_reward(412)` → 450 档；`next_reward(450)` → 500 档（返回**首个 layers > current** 的档）；`next_reward(1250)` → None
- 加载即全量校验（fail-fast），运行期不再防御

## 4. rules_check CLI

`python -m tft_copilot` 增加子命令（`__main__.py` 已有骨架）：

```
python -m tft_copilot rules-check [--patch 18.6]
```

输出：任务数/奖励档数/钥匙数/路线数统计 + 各类别计数 + 校验结果。AC1 的验收载体。

## 5. 测试设计（≥12 用例）

| 组 | 用例 |
|---|---|
| 加载 | 正常加载 18.6；文件缺失抛错；meta.patch 与文件名不符抛 VersionMismatchError；schema_version=99 抛 SchemaVersionError |
| 校验 | 删 task.variants 抛错；tier 非法枚举抛错；routes 引用不存在的 task id 抛错；rewards.layers 非升序抛错 |
| 查询 | get_task 命中/未命中；tasks_by_stage_route(4,"lose_streak") 内容与顺序；tasks_by_tier("good") 计数；next_reward 412/450/1250 边界 |

校验类用例用 `tmp_path` 写篡改副本再加载，不污染真实数据文件。

## 6. 红线自查

本迭代零感知、零网络、零输入——三红线天然满足。semgrep 规则预期零命中，作为门禁照跑（流程一致性）。

## 7. 工作量

实现 + 测试 + 文档 ≈ 半个工作日（数据录入占大头，38 任务 × 5 阶段变体约 190 行 JSON）。
