# -*- coding: utf-8 -*-
"""端到端模拟真机 OCR 读数，验证运营提示链路。"""
import sys

sys.path.insert(0, r"D:\tft-copilot")

from tft_copilot.knowledge.rules_loader import load_rules
from tft_copilot.knowledge.units_loader import UnitsBook
from tft_copilot.knowledge.traits_loader import load_traits
from tft_copilot.knowledge.equips_loader import load_equips
from tft_copilot.paths import bundle_data_dir
from tft_copilot.decision.engine import DecisionEngine
from tft_copilot.decision.snapshot import BoardSnapshot

book = UnitsBook.from_file(bundle_data_dir() / "units" / "units_18.6.json")
engine = DecisionEngine(
    load_rules(), book, store=None, traits_book=load_traits(), equips_book=load_equips()
)
mid = engine.start_match()
print("match_id:", mid)

# 回合1：层8 金2 血8 级1（与昨天 exe 冒烟读数一致）
snap = BoardSnapshot(
    round_no=1, scene="shop", quality=0.8, my_units=[], layers=8, hp=8, gold=2, level=1
)
advices = engine.on_round(snap)
print(f"回合1 建议 {len(advices)} 条:")
for a in advices:
    print(f"  [{a.level}] {a.text}  (来源:{a.source})")

# 回合2：层数推进到 9（10 层里程碑前 1 层，应触发 pre 提示）
snap2 = BoardSnapshot(
    round_no=2, scene="battle", quality=0.8, my_units=[], layers=9, hp=8, gold=2, level=1
)
advices2 = engine.on_round(snap2)
print(f"回合2 建议 {len(advices2)} 条:")
for a in advices2:
    print(f"  [{a.level}] {a.text}  (来源:{a.source})")

# 回合3：达标 10 层（应触发 hit 提示）
snap3 = BoardSnapshot(
    round_no=3, scene="battle", quality=0.8, my_units=[], layers=10, hp=8, gold=2, level=1
)
advices3 = engine.on_round(snap3)
print(f"回合3 建议 {len(advices3)} 条:")
for a in advices3:
    print(f"  [{a.level}] {a.text}  (来源:{a.source})")
