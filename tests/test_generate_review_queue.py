import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATE_REVIEW_QUEUE_PATH = REPO_ROOT / "scripts" / "generate_review_queue.py"
spec = importlib.util.spec_from_file_location(
    "generate_review_queue", GENERATE_REVIEW_QUEUE_PATH
)
generate_review_queue = importlib.util.module_from_spec(spec)
sys.modules["generate_review_queue"] = generate_review_queue
spec.loader.exec_module(generate_review_queue)


class GenerateReviewQueueTests(unittest.TestCase):
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

    def test_generates_review_items_for_low_quality_and_error_nodes(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "title": "x",
                        "children_status": "pending",
                        "children": [],
                    },
                    {
                        "id": "Q1",
                        "title": "错误节点",
                        "children_status": "error",
                        "last_error": "测试错误",
                        "children": [],
                    },
                ],
            },
        )

        queue = generate_review_queue.generate_review_queue(
            self.data_dir,
            limit=20,
            threshold=45,
        )

        titles = [item["title"] for item in queue["items"]]
        self.assertIn("x", titles)
        self.assertIn("错误节点", titles)
        self.assertEqual(queue["total_items"], len(queue["items"]))
        self.assertGreaterEqual(queue["total_candidates"], queue["total_items"])
        self.assertTrue(
            all(item.get("primary_reason") for item in queue["items"])
        )

    def test_reason_distribution_summarizes_major_review_causes(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "M1",
                        "children_status": "loaded",
                        "children": [],
                    },
                    {
                        "id": "Q2",
                        "title": "错误节点",
                        "children_status": "error",
                        "last_error": "测试错误",
                        "children": [],
                    },
                    {
                        "title": "x",
                        "children_status": "pending",
                        "children": [],
                    },
                ],
            },
        )

        queue = generate_review_queue.generate_review_queue(
            self.data_dir,
            limit=20,
            threshold=45,
        )
        distribution = queue["reason_distribution"]
        categories = {
            category["key"]: category
            for category in distribution["categories"]
        }

        self.assertEqual(distribution["total_items"], queue["total_items"])
        self.assertGreaterEqual(categories["non_zh_label"]["count"], 1)
        self.assertGreaterEqual(categories["error"]["count"], 1)
        self.assertGreaterEqual(categories["low_quality"]["count"], 1)
        self.assertTrue(categories["non_zh_label"]["sample_review_keys"])
        self.assertTrue(
            any(
                entry["reason"] == "non_zh_label"
                for entry in distribution["raw_reasons"]
            )
        )
        self.assertTrue(
            any(
                entry["status"] == "error"
                for entry in distribution["children_statuses"]
            )
        )

    def test_allowlisted_duplicate_is_not_review_item_by_itself(self):
        self.write_json(
            "validation_allowlist.json",
            {
                "duplicate_ids": {
                    "Q20": "合法多路径"
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
                        "id": "Q20",
                        "title": "合法重复一",
                        "children_status": "pending",
                        "source_relation": "subclass",
                        "children": [],
                    },
                    {
                        "id": "Q20",
                        "title": "合法重复二",
                        "children_status": "pending",
                        "source_relation": "subclass",
                        "children": [],
                    },
                ],
            },
        )

        queue = generate_review_queue.generate_review_queue(
            self.data_dir,
            limit=20,
            threshold=45,
        )

        self.assertFalse(
            any(
                "allowed_duplicate_id:2" in item.get("quality_reasons", [])
                for item in queue["items"]
            )
        )

    def test_unallowlisted_duplicate_gets_review_action(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q20",
                        "title": "重复一",
                        "children_status": "pending",
                        "source_relation": "subclass",
                        "children": [],
                    },
                    {
                        "id": "Q20",
                        "title": "重复二",
                        "children_status": "pending",
                        "source_relation": "subclass",
                        "children": [],
                    },
                ],
            },
        )

        queue = generate_review_queue.generate_review_queue(
            self.data_dir,
            limit=20,
            threshold=45,
        )

        duplicate_items = [
            item
            for item in queue["items"]
            if "duplicate_id:2" in item.get("quality_reasons", [])
        ]
        self.assertEqual(len(duplicate_items), 2)
        self.assertTrue("validation_allowlist" in duplicate_items[0]["suggested_action"])

    def test_main_writes_review_queue_file(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "title": "x",
                        "children_status": "pending",
                        "children": [],
                    }
                ],
            },
        )

        queue = generate_review_queue.generate_review_queue(self.data_dir, limit=10)
        generate_review_queue.save_json(
            self.data_dir / "review_queue.json",
            queue,
        )

        self.assertTrue((self.data_dir / "review_queue.json").exists())

    def test_review_decision_suppresses_item(self):
        self.write_json(
            "review_decisions.json",
            {
                "decisions": {
                    "location:root.json.children[0]": {
                        "status": "confirmed",
                        "reason": "已人工确认",
                        "updated_at": "2026-05-07T00:00:00Z",
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
                        "title": "x",
                        "children_status": "pending",
                        "children": [],
                    }
                ],
            },
        )

        queue = generate_review_queue.generate_review_queue(self.data_dir, limit=10)

        self.assertEqual(queue["total_candidates"], 1)
        self.assertEqual(queue["suppressed_items"], 1)
        self.assertEqual(queue["items"], [])

    def test_export_filters_review_items_by_reason(self):
        self.write_json(
            "root.json",
            {
                "id": "root",
                "title": "万物",
                "children_status": "loaded",
                "children": [
                    {
                        "id": "Q1",
                        "title": "M1",
                        "children_status": "loaded",
                        "children": [],
                    },
                    {
                        "id": "Q2",
                        "title": "错误节点",
                        "children_status": "error",
                        "last_error": "测试错误",
                        "children": [],
                    },
                ],
            },
        )
        queue = generate_review_queue.generate_review_queue(
            self.data_dir,
            limit=20,
            threshold=45,
        )
        output_path = Path(self.temp_dir.name) / "missing_zh.csv"

        exported = generate_review_queue.export_review_items(
            queue,
            output_path,
            reason="non_zh_label",
            export_format="csv",
        )

        text = output_path.read_text(encoding="utf-8-sig")
        self.assertGreaterEqual(exported, 1)
        self.assertIn("review_key", text)
        self.assertIn("M1", text)
        self.assertNotIn("错误节点", text)


if __name__ == "__main__":
    unittest.main()
