"""M1-2 units 数值库加载器测试：加载/校验/查询/去重 四组."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tft_copilot.knowledge.units_loader import (
    EXPECTED_SCHEMA_VERSION,
    UnitsBook,
    UnitsDataError,
)


def _unit(**overrides):
    base = {
        "id": "11400",
        "name": "测试弈子",
        "alias": [],
        "cost": 1,
        "traits": ["羁绊A", "羁绊B"],
        "attack_speed": 0.75,
        "range": 1,
        "mana_start": 0,
        "mana_max": 30,
        "crit": 0.25,
        "stars": [
            {"star": 1, "hp": 650, "ad": 40, "ar": 35, "mr": 35, "crit": 0.25},
            {"star": 2, "hp": 1170, "ad": 60, "ar": 35, "mr": 35, "crit": 0.25},
        ],
        "skill": {"name": "破败王剑", "type": "active", "detail": "x", "scales": ["10%", "55/85/125"]},
        "unlock": {"is_unlockable": False, "condition": None, "price": None},
        "quality_flags": [],
    }
    base.update(overrides)
    return base


def _payload(units=None, redundant=None, patch="18.6", fname="units_18.6.json"):
    return {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "meta": {
            "patch": patch,
            "source_page_version": "18.18.1",
            "mode_code": "16_18.18.1_S400001",
            "source": "test",
            "fetched_at": "2026-11-18T00:00:00+08:00",
            "entry_count": len(units if units is not None else [_unit()]),
        },
        "redundant_ids": redundant or [],
        "units": units if units is not None else [_unit()],
    }, fname


def _write(tmp_path: Path, payload, fname) -> Path:
    f = tmp_path / fname
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return f


# ---------- 加载组 ----------


class TestLoad:
    def test_load_ok(self, tmp_path):
        payload, fname = _payload()
        book = UnitsBook.from_file(_write(tmp_path, payload, fname))
        assert len(book) == 1

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            UnitsBook.from_file(tmp_path / "nope.json")

    def test_load_real_file(self):
        real = Path(__file__).resolve().parents[2] / "data" / "units" / "units_18.6.json"
        if not real.exists():  # fetch 未跑时跳过（CI 无数据场景）
            pytest.skip("units_18.6.json 未生成")
        book = UnitsBook.from_file(real)
        assert len(book) >= 100

    def test_load_bad_json(self, tmp_path):
        f = tmp_path / "units_18.6.json"
        f.write_text("{broken", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            UnitsBook.from_file(f)


# ---------- 校验组 ----------


class TestValidate:
    def test_schema_version_mismatch(self, tmp_path):
        payload, fname = _payload()
        payload["schema_version"] = 99
        with pytest.raises(UnitsDataError, match="schema_version"):
            UnitsBook.from_file(_write(tmp_path, payload, fname))

    def test_patch_filename_mismatch(self, tmp_path):
        payload, fname = _payload()
        payload["meta"]["patch"] = "18.7"
        with pytest.raises(UnitsDataError, match="三重校验失败"):
            UnitsBook.from_file(_write(tmp_path, payload, fname))

    def test_entry_count_mismatch(self, tmp_path):
        payload, fname = _payload()
        payload["meta"]["entry_count"] = 999
        with pytest.raises(UnitsDataError, match="entry_count"):
            UnitsBook.from_file(_write(tmp_path, payload, fname))

    def test_star_row_incomplete(self, tmp_path):
        bad = _unit(stars=[{"star": 1, "hp": 650, "ad": 40}])
        payload, fname = _payload(units=[bad])
        with pytest.raises(UnitsDataError, match="五维不完整"):
            UnitsBook.from_file(_write(tmp_path, payload, fname))

    def test_star_non_int_rejected(self, tmp_path):
        """回归：star 为字符串/bool 时必须拒绝（M1 复审加固）。"""
        bad = _unit(stars=[{"star": "1", "hp": 650, "ad": 40, "ar": 35, "mr": 35}])
        payload, fname = _payload(units=[bad])
        with pytest.raises(UnitsDataError, match="star 非法"):
            UnitsBook.from_file(_write(tmp_path, payload, fname))

    def test_redundant_ref_missing(self, tmp_path):
        payload, fname = _payload(redundant=[["11400", "99999"]])
        with pytest.raises(UnitsDataError, match="redundant_ids"):
            UnitsBook.from_file(_write(tmp_path, payload, fname))


# ---------- 查询组 ----------


class TestQuery:
    def _book(self, tmp_path):
        payload, fname = _payload()
        return UnitsBook.from_file(_write(tmp_path, payload, fname))

    def test_get_unit(self, tmp_path):
        u = self._book(tmp_path).get_unit("11400")
        assert u.name == "测试弈子" and u.cost == 1

    def test_get_unit_missing(self, tmp_path):
        with pytest.raises(UnitsDataError):
            self._book(tmp_path).get_unit("00000")

    def test_find_by_name(self, tmp_path):
        assert len(self._book(tmp_path).find_by_name("测试弈子")) == 1

    def test_units_by_cost_trait(self, tmp_path):
        b = self._book(tmp_path)
        assert len(b.units_by_cost(1)) == 1
        assert len(b.units_by_trait("羁绊A")) == 1
        assert b.units_by_trait("不存在羁绊") == []


# ---------- 去重组 ----------


class TestDedup:
    def test_dedup_view(self, tmp_path):
        a = _unit()
        b = _unit(id="11401", traits=["羁绊A", "羁绊B"])  # 同name同cost同traits → 重复对
        payload, fname = _payload(units=[a, b], redundant=[["11400", "11401"]])
        payload["meta"]["entry_count"] = 2
        book = UnitsBook.from_file(_write(tmp_path, payload, fname))
        assert len(book) == 2
        assert len(book.dedup_view()) == 1
        assert book.dedup_view()[0].id == "11400"

    def test_trait_registry_dedup(self, tmp_path):
        a = _unit()
        b = _unit(id="11401")
        payload, fname = _payload(units=[a, b], redundant=[["11400", "11401"]])
        payload["meta"]["entry_count"] = 2
        book = UnitsBook.from_file(_write(tmp_path, payload, fname))
        reg = book.trait_registry()
        assert reg["羁绊A"] == 1  # 去重后只计一次
