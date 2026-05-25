import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_DATA_PATH = REPO_ROOT / "scripts" / "validate_data.py"
spec = importlib.util.spec_from_file_location("validate_data", VALIDATE_DATA_PATH)
validate_data = importlib.util.module_from_spec(spec)
sys.modules["validate_data"] = validate_data
spec.loader.exec_module(validate_data)


class ValidateDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"
        self.nodes_dir = self.data_dir / "nodes"
        self.nodes_dir.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, relative_path, data):
        path = self.data_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return path

    def validator(self):
        return validate_data.DataValidator(self.data_dir)

    def test_valid_tree_with_data_source_passes(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "宇宙",
                        "data_source": "nodes/Q1.json",
                        "children_status": "loaded",
                    }
                ],
            },
        )
        self.write_json(
            "nodes/Q1.json",
            {
                "id": "Q1",
                "title": "宇宙",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertEqual(validator.errors, [])
        self.assertEqual(validator.node_count, 3)
        self.assertEqual(validator.pointer_count, 1)

    def test_broken_data_source_is_error(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q404",
                        "title": "缺失",
                        "data_source": "nodes/missing.json",
                        "children_status": "pending",
                    }
                ],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 1)
        self.assertTrue(
            any("`data_source` 文件不存在" in error for error in validator.errors)
        )

    def test_invalid_json_reports_parse_error(self):
        root = self.data_dir / "root.json"
        root.parent.mkdir(parents=True, exist_ok=True)
        root.write_text('{"title": "坏 JSON",', encoding="utf-8")

        validator = self.validator()

        self.assertEqual(validator.validate(), 1)
        self.assertTrue(any("JSON 解析失败" in error for error in validator.errors))

    def test_unknown_node_field_is_schema_drift_warning(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
                "unexpected_field": True,
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertTrue(any("schema 漂移" in warning for warning in validator.warnings))

    def test_data_source_cycle_is_error(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "宇宙",
                        "data_source": "nodes/Q1.json",
                        "children_status": "loaded",
                    }
                ],
            },
        )
        self.write_json(
            "nodes/Q1.json",
            {
                "id": "Q1",
                "title": "宇宙",
                "data_source": "root.json",
                "children_status": "loaded",
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 1)
        self.assertTrue(any("循环引用" in error for error in validator.errors))

    def test_duplicate_id_is_warning_not_error(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "宇宙",
                        "children_status": "loaded",
                        "children": [],
                    },
                    {
                        "id": "Q1",
                        "title": "另一路径",
                        "children_status": "loaded",
                        "children": [],
                    },
                ],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertTrue(any("重复 ID" in warning for warning in validator.warnings))

    def test_known_external_source_ids_are_not_qid_warnings(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "wikipedia:zh:Category:寄生",
                        "title": "寄生",
                        "children_status": "pending",
                        "children": [],
                    },
                    {
                        "id": "conceptnet:/c/zh/子节点",
                        "title": "子节点",
                        "children_status": "pending",
                        "children": [],
                    },
                    {
                        "id": "dbpedia:Category:Astrobiology",
                        "title": "Astrobiology",
                        "children_status": "pending",
                        "children": [],
                    },
                ],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertFalse(any("Wikidata QID" in warning for warning in validator.warnings))

    def test_allowlisted_duplicate_id_suppresses_warning(self):
        self.write_json(
            "validation_allowlist.json",
            {
                "duplicate_ids": {
                    "Q1": {
                        "reason": "测试同一个 Wikidata 节点可以出现在多条路径"
                    }
                }
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "宇宙",
                        "children_status": "loaded",
                        "children": [],
                    },
                    {
                        "id": "Q1",
                        "title": "另一路径",
                        "children_status": "loaded",
                        "children": [],
                    },
                ],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertFalse(any("重复 ID" in warning for warning in validator.warnings))
        self.assertEqual(validator.allowed_duplicate_hits, {"Q1"})

    def test_allowlisted_duplicate_data_source_pointers_suppress_warning(self):
        self.write_json(
            "validation_allowlist.json",
            {
                "duplicate_ids": {
                    "Q1": "测试同一个分片可以被多条路径引用"
                }
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "路径一",
                        "data_source": "nodes/Q1.json",
                        "children_status": "loaded",
                    },
                    {
                        "id": "Q1",
                        "title": "路径二",
                        "data_source": "nodes/Q1.json",
                        "children_status": "loaded",
                    },
                ],
            },
        )
        self.write_json(
            "nodes/Q1.json",
            {
                "id": "Q1",
                "title": "共享节点",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertFalse(any("重复 ID" in warning for warning in validator.warnings))
        self.assertFalse(any("可能可以移除" in warning for warning in validator.warnings))
        self.assertEqual(validator.allowed_duplicate_hits, {"Q1"})

    def test_stale_allowlisted_duplicate_id_warns(self):
        self.write_json(
            "validation_allowlist.json",
            {
                "duplicate_ids": {
                    "Q2": "测试过期允许项"
                }
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "宇宙",
                        "children_status": "loaded",
                        "children": [],
                    }
                ],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertTrue(
            any("可能可以移除" in warning for warning in validator.warnings)
        )

    def test_invalid_allowlist_entry_is_error(self):
        self.write_json(
            "validation_allowlist.json",
            {
                "duplicate_ids": {
                    "Q1": {
                        "reason": ""
                    }
                }
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 1)
        self.assertTrue(
            any("必须填写非空 `reason`" in error for error in validator.errors)
        )

    def test_valid_curation_file_passes(self):
        self.write_json(
            "curation.json",
            {
                "focused_node_ids": {
                    "Q1": {
                        "reason": "根路径重点",
                        "priority_bonus": 24,
                    }
                },
                "focused_titles": {
                    "人工节点": "人工维护重点"
                },
                "notes": "测试",
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertFalse(any("curation.json" in error for error in validator.errors))

    def test_invalid_curation_file_is_error(self):
        self.write_json(
            "curation.json",
            {
                "focused_node_ids": {
                    "not-qid": {
                        "reason": "",
                        "priority_bonus": "high",
                    }
                }
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 1)
        self.assertTrue(any("Wikidata QID" in error for error in validator.errors))
        self.assertTrue(any("priority_bonus" in error for error in validator.errors))

    def test_valid_review_queue_passes(self):
        self.write_json(
            "review_queue.json",
            {
                "generated_at": "2026-05-07T00:00:00Z",
                "threshold": 45,
                "limit": 20,
                "total_candidates": 1,
                "suppressed_items": 0,
                "decision_file": "review_decisions.json",
                "total_items": 1,
                "reason_distribution": {
                    "total_items": 1,
                    "categories": [
                        {
                            "key": "missing_id",
                            "label": "缺少 Wikidata QID",
                            "count": 1,
                            "sample_review_keys": ["location:root.json.children[0]"],
                        }
                    ],
                    "raw_reasons": [
                        {
                            "reason": "missing_id",
                            "count": 1,
                        }
                    ],
                    "children_statuses": [
                        {
                            "status": "pending",
                            "label": "待扩展",
                            "count": 1,
                        }
                    ],
                },
                "items": [
                    {
                        "title": "待审节点",
                        "path": "万物 / 待审节点",
                        "location": "root.json.children[0]",
                        "review_key": "location:root.json.children[0]",
                        "priority": 88,
                        "quality_score": 28,
                        "review_status": "needs_review",
                        "quality_reasons": ["missing_id"],
                        "suggested_action": "补充 Wikidata QID。",
                    }
                ],
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertFalse(any("review_queue.json" in error for error in validator.errors))

    def test_invalid_review_queue_is_error(self):
        self.write_json(
            "review_queue.json",
            {
                "generated_at": "2026-05-07T00:00:00Z",
                "threshold": 45,
                "limit": 20,
                "total_candidates": 1,
                "suppressed_items": 0,
                "decision_file": "review_decisions.json",
                "total_items": 2,
                "reason_distribution": {
                    "total_items": "bad",
                    "categories": [
                        {
                            "key": "low_quality",
                            "label": "低质量分",
                            "count": "many",
                            "sample_review_keys": "bad",
                        }
                    ],
                    "raw_reasons": [
                        {
                            "reason": "missing_id",
                            "count": "many",
                        }
                    ],
                    "children_statuses": [
                        {
                            "status": "pending",
                            "label": "待扩展",
                            "count": "many",
                        }
                    ],
                },
                "items": [
                    {
                        "title": "",
                        "path": "万物",
                        "location": "root.json",
                        "review_key": "",
                        "priority": "high",
                        "quality_score": 200,
                        "review_status": "unknown",
                        "quality_reasons": "missing_id",
                        "suggested_action": "",
                    }
                ],
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 1)
        self.assertTrue(any("total_items" in error for error in validator.errors))
        self.assertTrue(any("priority" in error for error in validator.errors))
        self.assertTrue(
            any("reason_distribution" in error for error in validator.errors)
        )

    def test_valid_review_decisions_pass(self):
        self.write_json(
            "review_decisions.json",
            {
                "decisions": {
                    "id:Q1": {
                        "status": "confirmed",
                        "reason": "已确认",
                        "updated_at": "2026-05-07T00:00:00Z",
                        "reviewed_by": "test",
                    }
                },
                "notes": "测试",
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertFalse(any("review_decisions.json" in error for error in validator.errors))

    def test_invalid_review_decisions_are_error(self):
        self.write_json(
            "review_decisions.json",
            {
                "decisions": {
                    "bad-key": {
                        "status": "unknown",
                        "reason": "",
                        "updated_at": 1,
                        "reviewed_by": 2,
                    }
                }
            },
        )
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 1)
        self.assertTrue(any("status" in error for error in validator.errors))
        self.assertTrue(any("复核 key" in error for error in validator.errors))

    def test_valid_end_nodes_scan_state_and_static_api_pass(self):
        end_payload = {
            "endpoint": "endNode",
            "generated_at": "2026-05-14T00:00:00Z",
            "fetch_strategy_version": 2,
            "total_items": 1,
            "items": [
                {
                    "key": "id:Q99",
                    "path": "nodes/Q99.json",
                    "title": "终止节点",
                    "reason": "wikidata_no_children",
                    "node": {
                        "id": "Q99",
                        "title": "终止节点",
                        "children_status": "loaded",
                        "is_leaf": True,
                    },
                }
            ],
        }
        self.write_json("end_nodes.json", end_payload)
        self.write_json(
            "scan_state.json",
            {
                "updated_at": "2026-05-14T00:00:00Z",
                "fetch_strategy_version": 2,
                "scan_order": "priority-depth-first-cursor-v1",
                "last_scan_key": "id:Q99",
                "candidate_count": 1,
                "selected_count": 1,
                "request_count": 1,
                "max_requests": 20,
                "exhausted": True,
            },
        )
        self.write_json("api/getEndNode.json", end_payload)
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [],
            },
        )

        validator = self.validator()

        self.assertEqual(validator.validate(), 0)
        self.assertFalse(any("end_nodes.json" in error for error in validator.errors))


if __name__ == "__main__":
    unittest.main()
