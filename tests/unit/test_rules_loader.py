"""rules_loader 单元测试：加载 / 校验 / 查询 三组。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tft_copilot.knowledge import (
    RulesValidationError,
    SchemaVersionError,
    VersionMismatchError,
    load_rules,
)

REPO_RULES = Path(__file__).resolve().parents[2] / "data" / "rules"


def _load_ok():
    return load_rules(patch="18.6")


def _tamper(mutate, tmp_path: Path):
    """读取真实 JSON，应用篡改函数，写入临时目录后返回其路径。"""
    raw = json.loads((REPO_RULES / "rules_18.6.json").read_text(encoding="utf-8"))
    mutate(raw)
    d = tmp_path / "rules"
    d.mkdir()
    f = d / "rules_18.6.json"
    f.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# 加载组
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_186_ok(self):
        b = _load_ok()
        assert b.patch == "18.6"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RulesValidationError, match="不存在"):
            load_rules(patch="99.9", data_dir=tmp_path)

    def test_version_mismatch_raises(self, tmp_path):
        def m(raw):
            raw["meta"]["patch"] = "18.7"

        d = _tamper(m, tmp_path)
        with pytest.raises(VersionMismatchError):
            load_rules(patch="18.6", data_dir=d)

    def test_schema_version_too_new_raises(self, tmp_path):
        def m(raw):
            raw["meta"]["schema_version"] = 99

        d = _tamper(m, tmp_path)
        with pytest.raises(SchemaVersionError):
            load_rules(patch="18.6", data_dir=d)


# ---------------------------------------------------------------------------
# 校验组
# ---------------------------------------------------------------------------


class TestValidate:
    def test_remove_variants_raises(self, tmp_path):
        def m(raw):
            raw["tasks"][0]["variants"] = []

        d = _tamper(m, tmp_path)
        with pytest.raises(RulesValidationError, match="variants"):
            load_rules(patch="18.6", data_dir=d)

    def test_bad_tier_raises(self, tmp_path):
        def m(raw):
            raw["tasks"][0]["tier"] = "神推荐"

        d = _tamper(m, tmp_path)
        with pytest.raises(RulesValidationError, match="tier 非法"):
            load_rules(patch="18.6", data_dir=d)

    def test_route_dangling_task_ref_raises(self, tmp_path):
        def m(raw):
            raw["routes"][0]["stage_23_tasks"] = ["no_such_task"]

        d = _tamper(m, tmp_path)
        with pytest.raises(RulesValidationError, match="引用不存在的任务"):
            load_rules(patch="18.6", data_dir=d)

    def test_rewards_not_ascending_raises(self, tmp_path):
        def m(raw):
            raw["rewards"][0]["layers"] = 500

        d = _tamper(m, tmp_path)
        with pytest.raises(RulesValidationError, match="升序唯一"):
            load_rules(patch="18.6", data_dir=d)

    def test_task_route_backref_dangling_raises(self, tmp_path):
        def m(raw):
            raw["tasks"][0]["routes"] = ["no_such_route"]

        d = _tamper(m, tmp_path)
        with pytest.raises(RulesValidationError, match="引用不存在的路线"):
            load_rules(patch="18.6", data_dir=d)


# ---------------------------------------------------------------------------
# 查询组
# ---------------------------------------------------------------------------


class TestQuery:
    def test_get_task_hit(self):
        b = _load_ok()
        assert b.get_task("star_qiyana").name == "登场三星奇亚娜"

    def test_get_task_miss(self):
        b = _load_ok()
        with pytest.raises(KeyError):
            b.get_task("nope")

    def test_stage_route_lose_streak_stage4(self):
        b = _load_ok()
        out = b.tasks_by_stage_route(4, "lose_streak")
        ids = [t.id for t in out]
        # 推荐序：单位阵亡 → 击杀 → 利息
        assert ids == ["unit_death", "kill_enemies", "earn_interest"]
        layers = {t.id: t.variant_at(4).layers for t in out}
        assert layers["unit_death"] == 175
        assert layers["kill_enemies"] == 110
        assert layers["earn_interest"] == 120

    def test_stage_route_steady_stage2(self):
        b = _load_ok()
        out = b.tasks_by_stage_route(2, "steady")
        ids = [t.id for t in out]
        assert ids == ["refresh_medium", "bench_empty_4", "earn_interest"]

    def test_tasks_by_tier_good_count(self):
        b = _load_ok()
        goods = b.tasks_by_tier("good")
        assert len(goods) == 13
        assert all(t.tier == "good" for t in goods)

    def test_tasks_by_tier_invalid(self):
        b = _load_ok()
        with pytest.raises(ValueError):
            b.tasks_by_tier("神推荐")

    def test_next_reward_412(self):
        b = _load_ok()
        r = b.next_reward(412)
        assert r is not None and r.layers == 450

    def test_next_reward_450_then_500(self):
        b = _load_ok()
        assert b.next_reward(450).layers == 500

    def test_next_reward_top_returns_none(self):
        b = _load_ok()
        assert b.next_reward(1250) is None
        assert b.next_reward(99999) is None

    def test_reward_at_exact(self):
        b = _load_ok()
        assert b.reward_at(500).quality == "strong"
        assert b.reward_at(1234) is None

    def test_counts(self):
        b = _load_ok()
        assert len(b.tasks) == 38
        assert len(b.rewards) == 20
        assert len(b.keys) == 2
        assert len(b.routes) == 4
