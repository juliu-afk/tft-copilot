# 技术方案：M1-2 弈子数值库

- 版本：v1.0（2026-11-18）
- 对应 PRD：docs/prd/m1-2-units-db.md
- 复用 M1-1 已验证模式：三重版本校验、加载器结构、CLI 子命令、测试分组

## 1. 数据流

```
jinchanchan.fun/hero/16_18.18.1_S400001 (列表页, SSR)
        │ fetch_units.py (requests + BS4, 1req/s, 重试3次退避2s)
        ├─ raw_html/ 落盘原始HTML快照 (122页)
        ├─ 头像图 → data/templates/v18.6/portraits/{id}.png (M2模板原料)
        └─ 解析 → data/units/units_18.6.json (数值库)
                     │
                     ├─ units_loader.py 三重校验 + 查询接口
                     ├─ units-check CLI
                     └─ M3 战力评分 / M4 数据闭环 消费
```

## 2. JSON Schema（schema_version: 2）

```json
{
  "schema_version": 2,
  "meta": {
    "patch": "18.6",
    "source_page_version": "18.18.1",
    "mode_code": "16_18.18.1_S400001",
    "source": "jinchanchan.fun",
    "fetched_at": "2026-11-18T14:00:00+08:00",
    "entry_count": 122
  },
  "redundant_ids": [["11410", "11411"]],
  "units": [
    {
      "id": "11400",
      "name": "佛耶戈",
      "alias": [],
      "cost": 1,
      "traits": ["暗影岛", "迅击战士"],
      "attack_speed": 0.75,
      "range": 1,
      "mana_start": 0,
      "mana_max": 30,
      "crit": 0.25,
      "stars": [
        {"star": 1, "hp": 650, "ad": 40, "ar": 35, "mr": 35, "crit": 0.25}
      ],
      "skill": {
        "name": "破败王剑",
        "type": "active",
        "desc": "…原样保留…",
        "scales": ["10%", "55/85/125", "18/27/42"]
      },
      "unlock": {"is_unlockable": false, "condition": null, "price": null},
      "quality_flags": []
    }
  ]
}
```

### 字段规约

| 字段 | 类型 | 规约 |
|---|---|---|
| id | str | 站点 5 位 ID，首位=费用档（11xxx=1费） |
| stars[].star | int | 站点原始行号 1-6，含重复行，不归一化 |
| stars[] 五维 | int | hp/ad/ar/mr 必填；行级 crit 可空时继承顶层 |
| skill.scales | list[str] | 原样存站点档位文本，不拆数字（M3 用时再解析） |
| quality_flags | list[enum] | PRD §2 四枚举 |
| redundant_ids | list[list[str,str]] | name+cost+traits集合等价判重结果 |

### 为什么 skill.scales 存字符串

M3 战力评分 v1 只用五维面板 + 费用 + 羁绊计数，不消费技能数值；提前拆数字需定义"哪个数字对应哪档星级"，而站点 3 档 vs 6 行尚未对齐，拆了也是错的。存原样文本 + M4 实测反校后再定解析规则，是唯一不引入主观错误的路径。

## 3. 加载器接口（units_loader.py）

```python
class UnitsBook:
    def validate(self) -> list[str]        # 三重校验+行级五维检查+ID唯一性+redundant_ids引用检查
    def get_unit(self, unit_id) -> Unit    # KeyError → 自定义 UnitsDataError
    def find_by_name(self, name) -> list[Unit]  # 中文名精确匹配，返回列表（同名多版本）
    def units_by_cost(self, cost) -> list[Unit]
    def units_by_trait(self, trait) -> list[Unit]
    def dedup_view(self) -> list[Unit]     # 剔除 redundant_ids 中每对第二个，返回去重视图
    def trait_registry(self) -> dict[str, int]  # trait名 → 拥有该trait的独立条目数
```

- 校验规则：schema_version==2；meta.patch 与文件名一致；entry_count == len(units)；ID 唯一；每星级行五维完整；redundant_ids 中引用的 ID 必须存在且互不为自身
- 异常体系与 M1-1 一致：RulesDataError 的姊妹类 UnitsDataError（同基类 KnowledgeError）

## 4. fetch_units.py 设计

```
输入: --mode-code 16_18.18.1_S400001 --out data/units --raw-dir data/units/raw_html --templates data/templates/v18.6/portraits
流程: 列表页解析条目索引(id/name/cost/traits/详情URL/头像URL)
      → 逐条目: 详情页 GET(重试3/退避2s) → raw_html落盘 → BS4解析字段 → 结构化dict
      → 头像下载(1req/s, 失败不阻塞数值采集, 记missing_templates列表)
      → 判重扫描(name+cost+traits集合) → redundant_ids
      → meta组装(含source_page_version) → 写units_18.6.json
      → 摘要输出: 成功/失败/重试/重复对/quality_flags统计
```

- 限速 1req/s（模块级 sleep），UA 标识 `tft-copilot-research/0.1 (personal study)`
- 403/429 立即终止整批（PRD 风险条款）
- 网络层仅 requests+bs4（tools/ 白名单目录，semgrep 规则已放行该路径）

## 5. 里程碑与测试

- 单测分组：加载 4 / 校验 5 / 查询 4 / 去重 2 = 15 用例（tests/unit/test_units_loader.py）
- 门禁：pytest 全绿 → semgrep 主包扫描（tools/ 除外）→ ruff → 提交推送
- M1 收口：本迭代 + M1-1 已完成项 → roadmap M1 标 3/3
