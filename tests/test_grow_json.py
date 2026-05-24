import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GROW_JSON_PATH = REPO_ROOT / "scripts" / "grow_json.py"
spec = importlib.util.spec_from_file_location("grow_json", GROW_JSON_PATH)
grow_json = importlib.util.module_from_spec(spec)
sys.modules["grow_json"] = grow_json
spec.loader.exec_module(grow_json)


class GrowJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"
        self.nodes_dir = self.data_dir / "nodes"
        self.nodes_dir.mkdir(parents=True)

        self.original_paths = {
            "DATA_DIR": grow_json.DATA_DIR,
            "NODES_DIR": grow_json.NODES_DIR,
            "ROOT_FILE": grow_json.ROOT_FILE,
            "STATS_FILE": grow_json.STATS_FILE,
            "GROWTH_HISTORY_FILE": grow_json.GROWTH_HISTORY_FILE,
            "CURATION_FILE": grow_json.CURATION_FILE,
            "VALIDATION_ALLOWLIST_FILE": grow_json.VALIDATION_ALLOWLIST_FILE,
            "END_NODES_FILE": grow_json.END_NODES_FILE,
            "SCAN_STATE_FILE": grow_json.SCAN_STATE_FILE,
            "API_DIR": grow_json.API_DIR,
            "CURATION_CACHE": grow_json.CURATION_CACHE,
            "DUPLICATE_ID_COUNTS": grow_json.DUPLICATE_ID_COUNTS,
            "ALLOWED_DUPLICATE_IDS": grow_json.ALLOWED_DUPLICATE_IDS,
            "MAX_REQUESTS": grow_json.MAX_REQUESTS,
            "MAX_SOURCES_PER_NODE": grow_json.MAX_SOURCES_PER_NODE,
            "REQUEST_DELAY": grow_json.REQUEST_DELAY,
            "WIKIDATA_REQUEST_DELAY": grow_json.WIKIDATA_REQUEST_DELAY,
            "SOURCE_ORDER": grow_json.SOURCE_ORDER,
            "SOURCE_COOLDOWN_SECONDS": grow_json.SOURCE_COOLDOWN_SECONDS,
            "TRANSIENT_SOURCE_COOLDOWN_SECONDS": grow_json.TRANSIENT_SOURCE_COOLDOWN_SECONDS,
            "IGNORE_SOURCE_COOLDOWN": grow_json.IGNORE_SOURCE_COOLDOWN,
            "fetch_wikidata_children": grow_json.fetch_wikidata_children,
            "fetch_wikidata_api_children": grow_json.fetch_wikidata_api_children,
            "fetch_wikipedia_children": grow_json.fetch_wikipedia_children,
            "fetch_conceptnet_children": grow_json.fetch_conceptnet_children,
            "DEFAULT_FOCUS_PRIORITY_BONUS": grow_json.DEFAULT_FOCUS_PRIORITY_BONUS,
        }

        grow_json.DATA_DIR = self.data_dir
        grow_json.NODES_DIR = self.nodes_dir
        grow_json.ROOT_FILE = self.data_dir / "root.json"
        grow_json.STATS_FILE = self.data_dir / "stats.json"
        grow_json.GROWTH_HISTORY_FILE = self.data_dir / "growth_history.json"
        grow_json.CURATION_FILE = self.data_dir / "curation.json"
        grow_json.VALIDATION_ALLOWLIST_FILE = self.data_dir / "validation_allowlist.json"
        grow_json.END_NODES_FILE = self.data_dir / "end_nodes.json"
        grow_json.SCAN_STATE_FILE = self.data_dir / "scan_state.json"
        grow_json.API_DIR = self.data_dir / "api"
        grow_json.CURATION_CACHE = None
        grow_json.DUPLICATE_ID_COUNTS = {}
        grow_json.ALLOWED_DUPLICATE_IDS = set()
        grow_json.MAX_REQUESTS = 0
        grow_json.MAX_SOURCES_PER_NODE = 1
        grow_json.REQUEST_DELAY = 0
        grow_json.WIKIDATA_REQUEST_DELAY = 0
        grow_json.SOURCE_ORDER = ["wikidata"]
        grow_json.SOURCE_COOLDOWN_SECONDS = 3600
        grow_json.TRANSIENT_SOURCE_COOLDOWN_SECONDS = 600
        grow_json.IGNORE_SOURCE_COOLDOWN = False
        grow_json.DEFAULT_FOCUS_PRIORITY_BONUS = 18
        grow_json.request_count = 0
        grow_json.nodes_added_this_run = 0
        grow_json.nodes_scanned_this_run = 0
        grow_json.failed_requests_this_run = 0
        grow_json.unchanged_requests_this_run = 0
        grow_json.end_nodes_marked_this_run = 0
        grow_json.scan_candidate_count = 0
        grow_json.scan_exhausted = False
        grow_json.last_scan_key_this_run = ""
        grow_json.last_scan_title_this_run = ""
        grow_json.run_stop_reason = ""
        grow_json.source_request_counts = {}
        grow_json.source_cooldowns_this_run = {}
        grow_json.last_source_request_at = {}

    def tearDown(self):
        for name, value in self.original_paths.items():
            setattr(grow_json, name, value)
        self.temp_dir.cleanup()

    def test_merge_children_deduplicates_without_overwriting_manual_fields(self):
        existing = [
            {
                "id": "Q1",
                "title": "人工标题",
                "children_status": "manual",
                "children": [{"title": "人工子节点"}],
                "source_relation": "manual",
                "manual_note": "保留",
            }
        ]
        fetched = [
            {"id": "Q1", "title": "自动标题", "source_relation": "subclass"},
            {"id": "Q2", "title": "新增节点", "source_relation": "subclass"},
            {"id": "Q2", "title": "重复节点", "source_relation": "instance"},
        ]

        merged, added = grow_json.merge_children(existing, fetched)

        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["title"], "人工标题")
        self.assertEqual(merged[0]["source_relation"], "manual")
        self.assertEqual(merged[0]["manual_note"], "保留")
        self.assertEqual(merged[1]["id"], "Q2")
        self.assertEqual(merged[1]["title"], "新增节点")

    def test_materialize_child_creates_shard_and_updates_pointer(self):
        child = {
            "id": "Q42",
            "title": "测试节点",
            "children_status": "pending",
            "children": [{"title": "内联子节点"}],
            "source_relation": "subclass",
        }

        child_data, path, changed = grow_json.materialize_child(child)

        self.assertTrue(changed)
        self.assertEqual(path, self.nodes_dir / "Q42.json")
        self.assertTrue(path.exists())
        self.assertEqual(child["data_source"], "nodes/Q42.json")
        self.assertEqual(child["id"], "Q42")
        self.assertEqual(child["title"], "测试节点")
        self.assertIn("quality_score", child)
        self.assertEqual(child_data["children"][0]["title"], "内联子节点")

    def test_materialize_child_preserves_existing_shard_manual_content(self):
        shard = self.nodes_dir / "Q42.json"
        grow_json.save_json(
            shard,
            {
                "id": "Q42",
                "title": "人工维护标题",
                "children_status": "manual",
                "children": [{"title": "人工子节点"}],
                "manual_note": "不能覆盖",
            },
        )
        child = {
            "id": "Q42",
            "title": "自动标题",
            "data_source": "nodes/Q42.json",
            "children_status": "pending",
            "children": [],
        }

        child_data, _, changed = grow_json.materialize_child(child)

        self.assertTrue(changed)
        self.assertEqual(child_data["title"], "人工维护标题")
        self.assertEqual(child_data["manual_note"], "不能覆盖")
        self.assertEqual(child["title"], "人工维护标题")
        self.assertEqual(child["children_status"], "manual")
        self.assertNotIn("children", child)

        with shard.open("r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["children"][0]["title"], "人工子节点")

    def test_quality_metadata_sets_review_status(self):
        approved = {
            "id": "Q1",
            "title": "宇宙",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }
        needs_review = {
            "title": "x",
            "children_status": "pending",
            "children": [],
        }

        grow_json.normalize_node(approved)
        grow_json.normalize_node(needs_review)

        self.assertEqual(approved["review_status"], "approved")
        self.assertEqual(needs_review["review_status"], "needs_review")
        self.assertFalse(grow_json.should_fetch(needs_review))

    def test_prioritized_children_prefers_pending_high_quality_nodes(self):
        low_quality = {
            "title": "x",
            "children_status": "pending",
            "children": [],
        }
        stale_loaded = {
            "id": "Q3",
            "title": "生命",
            "children_status": "loaded",
            "fetch_strategy_version": 1,
            "source_relation": "subclass",
            "children": [{"title": "子节点"}],
        }
        pending = {
            "id": "Q1",
            "title": "宇宙",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }
        for node in (low_quality, stale_loaded, pending):
            grow_json.normalize_node(node)

        ordered = grow_json.prioritized_children(
            [low_quality, stale_loaded, pending],
            depth=1,
        )

        self.assertEqual(ordered[0]["id"], "Q1")
        self.assertEqual(ordered[-1]["review_status"], "needs_review")

    def test_curation_focus_increases_quality_and_priority(self):
        grow_json.save_json(
            grow_json.CURATION_FILE,
            {
                "focused_node_ids": {
                    "Q9": {
                        "reason": "人工关注测试节点",
                        "priority_bonus": 40,
                    }
                }
            },
        )
        grow_json.CURATION_CACHE = None
        focused = {
            "id": "Q9",
            "title": "测试重点",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }
        plain = {
            "id": "Q10",
            "title": "普通节点",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }

        grow_json.normalize_node(focused)
        grow_json.normalize_node(plain)

        self.assertIn("curated_focus", focused["quality_reasons"])
        self.assertGreater(focused["quality_score"], plain["quality_score"])
        self.assertGreater(
            grow_json.expansion_priority(focused, depth=1),
            grow_json.expansion_priority(plain, depth=1),
        )

    def test_quality_metadata_marks_broad_and_disambiguation_titles(self):
        broad = {
            "id": "Q10",
            "title": "实体",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }
        disambiguation = {
            "id": "Q11",
            "title": "测试消歧义",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }

        grow_json.normalize_node(broad)
        grow_json.normalize_node(disambiguation)

        self.assertIn("broad_title", broad["quality_reasons"])
        self.assertIn("disambiguation", disambiguation["quality_reasons"])

    def test_duplicate_id_lowers_quality_when_not_allowlisted(self):
        duplicated = {
            "id": "Q20",
            "title": "重复节点",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }
        plain = {
            "id": "Q21",
            "title": "普通节点",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }
        grow_json.DUPLICATE_ID_COUNTS = {"Q20": 2}
        grow_json.ALLOWED_DUPLICATE_IDS = set()

        grow_json.normalize_node(duplicated)
        grow_json.normalize_node(plain)

        self.assertIn("duplicate_id:2", duplicated["quality_reasons"])
        self.assertLess(duplicated["quality_score"], plain["quality_score"])

    def test_allowlisted_duplicate_id_is_marked_without_penalty(self):
        node = {
            "id": "Q20",
            "title": "合法重复",
            "children_status": "pending",
            "source_relation": "subclass",
            "children": [],
        }
        grow_json.DUPLICATE_ID_COUNTS = {"Q20": 2}
        grow_json.ALLOWED_DUPLICATE_IDS = {"Q20"}

        grow_json.normalize_node(node)

        self.assertIn("allowed_duplicate_id:2", node["quality_reasons"])
        self.assertNotIn("duplicate_id:2", node["quality_reasons"])

    def test_prepare_quality_context_uses_validation_allowlist(self):
        grow_json.save_json(
            grow_json.VALIDATION_ALLOWLIST_FILE,
            {
                "duplicate_ids": {
                    "Q20": "测试合法重复"
                }
            },
        )
        root = {
            "id": "root",
            "title": "万物",
            "children_status": "loaded",
            "children": [
                {
                    "id": "Q20",
                    "title": "路径一",
                    "children_status": "pending",
                    "children": [],
                },
                {
                    "id": "Q20",
                    "title": "路径二",
                    "children_status": "pending",
                    "children": [],
                },
            ],
        }

        grow_json.prepare_quality_context(root)

        self.assertEqual(grow_json.DUPLICATE_ID_COUNTS["Q20"], 2)
        self.assertIn("Q20", grow_json.ALLOWED_DUPLICATE_IDS)

    def test_duplicate_id_counts_include_multiple_data_source_pointers_once_each(self):
        grow_json.save_json(
            self.nodes_dir / "Q20.json",
            {
                "id": "Q20",
                "title": "共享节点",
                "children_status": "loaded",
                "children": [],
            },
        )
        root = {
            "id": "root",
            "title": "万物",
            "children_status": "loaded",
            "children": [
                {
                    "id": "Q20",
                    "title": "路径一",
                    "data_source": "nodes/Q20.json",
                    "children_status": "loaded",
                },
                {
                    "id": "Q20",
                    "title": "路径二",
                    "data_source": "nodes/Q20.json",
                    "children_status": "loaded",
                },
            ],
        }

        counts = grow_json.collect_duplicate_id_counts(root)

        self.assertEqual(counts["Q20"], 2)

    def test_current_strategy_leaf_is_not_fetched_again(self):
        leaf = {
            "id": "Q99",
            "title": "终止节点",
            "children_status": "loaded",
            "fetch_strategy_version": grow_json.FETCH_STRATEGY_VERSION,
            "is_leaf": True,
            "children": [],
        }
        grow_json.normalize_node(leaf)
        grow_json.apply_end_metadata(leaf)

        self.assertEqual(leaf["end_reason"], "wikidata_no_children")
        self.assertFalse(grow_json.should_fetch(leaf))

    def test_rotate_candidates_continues_after_last_scan_key(self):
        candidates = [
            {"scan_key": "id:Q1", "priority": 10, "depth": 1},
            {"scan_key": "id:Q2", "priority": 9, "depth": 1},
            {"scan_key": "id:Q3", "priority": 8, "depth": 1},
        ]

        rotated = grow_json.rotate_candidates(candidates, "id:Q1")

        self.assertEqual([item["scan_key"] for item in rotated], ["id:Q2", "id:Q3", "id:Q1"])

    def test_old_strategy_scan_cursor_is_ignored(self):
        state = {
            "fetch_strategy_version": grow_json.FETCH_STRATEGY_VERSION - 1,
            "last_scan_key": "id:Q-old",
        }

        self.assertEqual(grow_json.cursor_from_scan_state(state), "")

    def test_current_strategy_scan_cursor_is_preserved(self):
        state = {
            "fetch_strategy_version": grow_json.FETCH_STRATEGY_VERSION,
            "last_scan_key": "id:Q-current",
        }

        self.assertEqual(grow_json.cursor_from_scan_state(state), "id:Q-current")

    def test_rate_limit_pauses_without_marking_node_error(self):
        node = {
            "id": "Q1",
            "title": "宇宙",
            "children_status": "pending",
            "children": [],
        }

        def rate_limited(_node, _blocked_ids=None):
            raise RuntimeError("HTTP Error 429: Aggressively rate-limiting to 1 req / min")

        grow_json.fetch_wikidata_children = rate_limited
        grow_json.SOURCE_ORDER = ["wikidata"]
        grow_json.MAX_REQUESTS = 1

        changed = grow_json.process_fetch_candidate(
            {
                "node": node,
                "file_path": self.nodes_dir / "Q1.json",
                "scan_key": "id:Q1",
                "title": "宇宙",
                "ancestor_ids": set(),
            },
            {},
        )

        self.assertFalse(changed)
        self.assertEqual(grow_json.request_count, 1)
        self.assertEqual(node["children_status"], "pending")
        self.assertNotIn("last_error", node)
        self.assertEqual(grow_json.run_stop_reason, "all_sources_in_cooldown")
        self.assertIn("wikidata", grow_json.source_cooldowns_this_run)
        self.assertEqual(grow_json.last_scan_key_this_run, "id:Q1")

    def test_transient_source_error_uses_shorter_cooldown(self):
        grow_json.TRANSIENT_SOURCE_COOLDOWN_SECONDS = 45

        grow_json.register_source_cooldown(
            "wikipedia",
            RuntimeError("HTTP Error 502: Bad Gateway"),
            "transient_error",
        )

        cooldown = grow_json.source_cooldowns_this_run["wikipedia"]
        self.assertEqual(cooldown["reason"], "transient_error")
        self.assertEqual(cooldown["retry_after_seconds"], 45)

    def test_ignore_source_cooldown_clears_previous_cooldowns(self):
        grow_json.save_json(
            grow_json.SCAN_STATE_FILE,
            {
                "source_cooldowns": {
                    "wikipedia": {
                        "source": "wikipedia",
                        "cooldown_until": "2999-01-01T00:00:00Z",
                    }
                }
            },
        )

        self.assertTrue(grow_json.source_in_cooldown("wikipedia"))
        grow_json.IGNORE_SOURCE_COOLDOWN = True

        self.assertFalse(grow_json.source_in_cooldown("wikipedia"))
        self.assertEqual(grow_json.active_source_cooldowns(), {})

    def test_wikipedia_fallback_after_wikidata_rate_limit_adds_children(self):
        node = {
            "id": "Q3",
            "title": "生命",
            "children_status": "pending",
            "children": [],
        }

        def rate_limited(_node, _blocked_ids=None):
            raise RuntimeError("HTTP Error 429: rate limit")

        def wikipedia_children(_node, _blocked_ids=None):
            return [
                {
                    "id": "wikipedia:zh:Category:生物学",
                    "title": "生物学",
                    "children_status": "pending",
                    "source_provider": "wikipedia",
                    "source_relation": "wikipedia_category",
                }
            ]

        grow_json.fetch_wikidata_children = rate_limited
        grow_json.fetch_wikipedia_children = wikipedia_children
        grow_json.SOURCE_ORDER = ["wikidata", "wikipedia"]
        grow_json.MAX_REQUESTS = 2
        grow_json.MAX_SOURCES_PER_NODE = 0

        changed = grow_json.process_fetch_candidate(
            {
                "node": node,
                "file_path": self.nodes_dir / "Q3.json",
                "scan_key": "id:Q3",
                "title": "生命",
                "ancestor_ids": set(),
            },
            {},
        )

        self.assertTrue(changed)
        self.assertEqual(grow_json.request_count, 2)
        self.assertEqual(grow_json.source_request_counts, {"wikidata": 1, "wikipedia": 1})
        self.assertEqual(node["children_status"], "loaded")
        self.assertEqual(node["last_fetch_source"], "wikipedia")
        self.assertEqual(node["last_fetch_sources"], ["wikipedia"])
        self.assertEqual(node["children"][0]["title"], "生物学")
        self.assertEqual(grow_json.last_scan_key_this_run, "id:Q3")

    def test_single_source_no_children_keeps_node_pending(self):
        node = {
            "id": "Q10",
            "title": "测试节点",
            "children_status": "pending",
            "children": [],
        }

        def wikipedia_empty(_node, _blocked_ids=None):
            return []

        def conceptnet_transient(_node, _blocked_ids=None):
            raise RuntimeError("HTTP Error 502: Bad Gateway")

        grow_json.fetch_wikipedia_children = wikipedia_empty
        grow_json.fetch_conceptnet_children = conceptnet_transient
        grow_json.SOURCE_ORDER = ["wikipedia", "conceptnet"]
        grow_json.MAX_REQUESTS = 2
        grow_json.MAX_SOURCES_PER_NODE = 0

        grow_json.process_fetch_candidate(
            {
                "node": node,
                "file_path": self.nodes_dir / "Q10.json",
                "scan_key": "id:Q10",
                "title": "测试节点",
                "ancestor_ids": set(),
            },
            {},
        )

        self.assertEqual(grow_json.request_count, 2)
        self.assertEqual(node["children_status"], "pending")
        self.assertFalse(node["is_leaf"])
        self.assertNotIn("end_reason", node)
        self.assertIn("wikipedia", node["source_no_children"])
        self.assertIn("conceptnet", node["last_source_errors"])
        self.assertIn("conceptnet", grow_json.source_cooldowns_this_run)

    def test_all_sources_no_children_marks_leaf(self):
        node = {
            "id": "Q11",
            "title": "测试叶子",
            "children_status": "pending",
            "children": [],
        }

        def empty_children(_node, _blocked_ids=None):
            return []

        grow_json.fetch_wikipedia_children = empty_children
        grow_json.fetch_conceptnet_children = empty_children
        grow_json.SOURCE_ORDER = ["wikipedia", "conceptnet"]
        grow_json.MAX_REQUESTS = 2
        grow_json.MAX_SOURCES_PER_NODE = 0

        grow_json.process_fetch_candidate(
            {
                "node": node,
                "file_path": self.nodes_dir / "Q11.json",
                "scan_key": "id:Q11",
                "title": "测试叶子",
                "ancestor_ids": set(),
            },
            {},
        )

        self.assertEqual(node["children_status"], "loaded")
        self.assertTrue(node["is_leaf"])
        self.assertEqual(node["end_reason"], "sources_no_children")
        self.assertEqual(
            set(node["source_no_children"]),
            {"wikipedia", "conceptnet"},
        )

    def test_source_no_children_is_skipped_on_next_run(self):
        node = {
            "id": "Q12",
            "title": "可继续节点",
            "children_status": "pending",
            "children": [],
            "source_no_children": {"wikipedia": "2026-05-14T00:00:00Z"},
        }

        def wikipedia_should_not_run(_node, _blocked_ids=None):
            raise AssertionError("wikipedia should be skipped")

        def conceptnet_children(_node, _blocked_ids=None):
            return [
                {
                    "id": "conceptnet:/c/zh/子节点",
                    "title": "子节点",
                    "children_status": "pending",
                    "source_provider": "conceptnet",
                }
            ]

        grow_json.fetch_wikipedia_children = wikipedia_should_not_run
        grow_json.fetch_conceptnet_children = conceptnet_children
        grow_json.SOURCE_ORDER = ["wikipedia", "conceptnet"]
        grow_json.MAX_REQUESTS = 1

        grow_json.process_fetch_candidate(
            {
                "node": node,
                "file_path": self.nodes_dir / "Q12.json",
                "scan_key": "id:Q12",
                "title": "可继续节点",
                "ancestor_ids": set(),
            },
            {},
        )

        self.assertEqual(grow_json.request_count, 1)
        self.assertEqual(node["last_fetch_source"], "conceptnet")
        self.assertEqual(node["children"][0]["title"], "子节点")

    def test_max_sources_per_node_checks_one_source_then_moves_on(self):
        node = {
            "id": "Q14",
            "title": "小预算节点",
            "children_status": "pending",
            "children": [],
        }

        def empty_children(_node, _blocked_ids=None):
            return []

        grow_json.fetch_wikipedia_children = empty_children
        grow_json.fetch_conceptnet_children = empty_children
        grow_json.SOURCE_ORDER = ["wikipedia", "conceptnet"]
        grow_json.MAX_REQUESTS = 2
        grow_json.MAX_SOURCES_PER_NODE = 1

        grow_json.process_fetch_candidate(
            {
                "node": node,
                "file_path": self.nodes_dir / "Q14.json",
                "scan_key": "id:Q14",
                "title": "小预算节点",
                "ancestor_ids": set(),
            },
            {},
        )

        self.assertEqual(grow_json.request_count, 1)
        self.assertEqual(node["children_status"], "pending")
        self.assertIn("wikipedia", node["source_no_children"])
        self.assertIn("wikipedia", node["source_checked"])
        self.assertNotIn("conceptnet", node.get("source_checked", {}))
        self.assertTrue(grow_json.source_can_fetch("conceptnet", node))

    def test_loaded_duplicate_source_stays_candidate_for_other_sources(self):
        node = {
            "id": "Q15",
            "title": "已有子节点",
            "children_status": "loaded",
            "fetch_strategy_version": grow_json.FETCH_STRATEGY_VERSION - 1,
            "children": [
                {
                    "id": "Q16",
                    "title": "已存在",
                    "children_status": "pending",
                }
            ],
        }

        def duplicate_child(_node, _blocked_ids=None):
            return [
                {
                    "id": "Q16",
                    "title": "已存在",
                    "children_status": "pending",
                    "source_provider": "wikidata",
                }
            ]

        grow_json.fetch_wikidata_children = duplicate_child
        grow_json.SOURCE_ORDER = ["wikidata", "wikipedia"]
        grow_json.MAX_REQUESTS = 1
        grow_json.MAX_SOURCES_PER_NODE = 1

        grow_json.process_fetch_candidate(
            {
                "node": node,
                "file_path": self.nodes_dir / "Q15.json",
                "scan_key": "id:Q15",
                "title": "已有子节点",
                "ancestor_ids": set(),
            },
            {},
        )

        self.assertEqual(grow_json.request_count, 1)
        self.assertEqual(node["children_status"], "loaded")
        self.assertIn("wikidata", node["source_checked"])
        self.assertNotEqual(node.get("fetch_strategy_version"), grow_json.FETCH_STRATEGY_VERSION)
        self.assertFalse(grow_json.source_can_fetch("wikidata", node))
        self.assertTrue(grow_json.source_can_fetch("wikipedia", node))
        self.assertTrue(grow_json.should_fetch(node))

    def test_legacy_wikidata_leaf_reopens_for_new_sources(self):
        node = {
            "id": "Q13",
            "title": "旧叶子",
            "children_status": "loaded",
            "children": [],
            "fetch_strategy_version": grow_json.FETCH_STRATEGY_VERSION - 1,
            "is_leaf": True,
            "end_reason": "wikidata_no_children",
            "ended_at": "2026-05-14T00:00:00Z",
        }
        grow_json.SOURCE_ORDER = ["wikidata", "wikipedia"]

        changed = grow_json.normalize_node(node)

        self.assertTrue(changed)
        self.assertEqual(node["children_status"], "pending")
        self.assertFalse(node["is_leaf"])
        self.assertEqual(node["source_no_children"], {"wikidata": "2026-05-14T00:00:00Z"})
        self.assertNotIn("end_reason", node)

    def test_write_static_api_includes_end_node_and_children_endpoint(self):
        root = {
            "id": "root",
            "title": "万物",
            "children_status": "loaded",
            "children": [
                {
                    "id": "Q99",
                    "title": "终止节点",
                    "data_source": "nodes/Q99.json",
                    "children_status": "loaded",
                    "fetch_strategy_version": grow_json.FETCH_STRATEGY_VERSION,
                    "is_leaf": True,
                }
            ],
        }
        grow_json.save_json(
            self.nodes_dir / "Q99.json",
            {
                "id": "Q99",
                "title": "终止节点",
                "children_status": "loaded",
                "fetch_strategy_version": grow_json.FETCH_STRATEGY_VERSION,
                "is_leaf": True,
                "updated_at": "2026-05-14T00:00:00Z",
                "children": [],
            },
        )

        summary = grow_json.write_static_api(root)

        self.assertEqual(len(summary["end_nodes"]), 1)
        end_node = grow_json.load_json(grow_json.API_DIR / "getEndNode.json")
        children_api = grow_json.load_json(grow_json.API_DIR / "children" / "nodes" / "Q99.json")
        node_api = grow_json.load_json(grow_json.API_DIR / "nodes" / "Q99.json")
        alias_node_api = grow_json.load_json(grow_json.API_DIR / "by-id" / "Q99" / "node.json")
        alias_children_api = grow_json.load_json(grow_json.API_DIR / "by-id" / "Q99" / "children.json")
        alias_index_api = grow_json.load_json(grow_json.API_DIR / "by-id" / "Q99" / "index.json")

        self.assertEqual(end_node["total_items"], 1)
        self.assertEqual(children_api["child_count"], 0)
        self.assertEqual(node_api["node"]["id"], "Q99")
        self.assertEqual(alias_node_api["node"]["id"], "Q99")
        self.assertEqual(alias_children_api["child_count"], 0)
        self.assertEqual(alias_index_api["id"], "Q99")

    def test_static_api_by_id_alias_encodes_non_qid_id(self):
        identifier = "wikipedia:zh:Category:寄生生物題材作品"
        root = {
            "id": "root",
            "title": "万物",
            "children_status": "loaded",
            "children": [
                {
                    "id": identifier,
                    "title": "寄生生物題材作品",
                    "children_status": "pending",
                    "children": [],
                }
            ],
        }

        grow_json.write_static_api(root)

        alias_dir = grow_json.API_DIR / "by-id" / grow_json.api_by_id_slug(identifier)
        alias_node_api = grow_json.load_json(alias_dir / "node.json")
        alias_index_api = grow_json.load_json(alias_dir / "index.json")

        self.assertTrue(alias_dir.exists())
        self.assertNotIn(":", alias_dir.name)
        self.assertEqual(alias_node_api["node"]["id"], identifier)
        self.assertEqual(alias_index_api["id"], identifier)

    def test_zero_request_refresh_can_skip_growth_history_append(self):
        grow_json.save_json(
            grow_json.GROWTH_HISTORY_FILE,
            [
                {
                    "run_at": "2026-05-13T00:00:00Z",
                    "added_nodes": 0,
                    "total_nodes": 1,
                }
            ],
        )

        grow_json.record_growth_history(1, 0, append_history=False)

        history = grow_json.load_json_array(grow_json.GROWTH_HISTORY_FILE)
        stats = grow_json.load_json(grow_json.STATS_FILE)
        self.assertEqual(len(history), 1)
        self.assertEqual(stats["history_entries"], 1)


if __name__ == "__main__":
    unittest.main()
