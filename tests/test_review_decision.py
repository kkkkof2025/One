import importlib.util
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_DECISION_PATH = REPO_ROOT / "scripts" / "review_decision.py"
spec = importlib.util.spec_from_file_location("review_decision", REVIEW_DECISION_PATH)
review_decision = importlib.util.module_from_spec(spec)
sys.modules["review_decision"] = review_decision
spec.loader.exec_module(review_decision)


class ReviewDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"

    def tearDown(self):
        self.temp_dir.cleanup()

    def read_decisions(self):
        with (self.data_dir / "review_decisions.json").open("r", encoding="utf-8") as f:
            return json.load(f)

    def read_curation(self):
        with (self.data_dir / "curation.json").open("r", encoding="utf-8") as f:
            return json.load(f)

    def read_allowlist(self):
        with (self.data_dir / "validation_allowlist.json").open(
            "r", encoding="utf-8"
        ) as f:
            return json.load(f)

    def run_quietly(self, func, args):
        with redirect_stdout(io.StringIO()):
            return func(args)

    def capture_output(self, func, args):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = func(args)
        return result, buffer.getvalue()

    def test_mark_records_decision_by_id(self):
        args = Namespace(
            data_dir=str(self.data_dir),
            key=None,
            id="Q1",
            location=None,
            title=None,
            status="confirmed",
            reason="已确认",
            reviewed_by="test",
            sync_curation=False,
            sync_allowlist=False,
            priority_bonus=None,
        )

        self.assertEqual(self.run_quietly(review_decision.command_mark, args), 0)
        data = self.read_decisions()

        self.assertEqual(data["decisions"]["id:Q1"]["status"], "confirmed")
        self.assertEqual(data["decisions"]["id:Q1"]["reviewed_by"], "test")

    def test_mark_curated_can_sync_curation_by_id(self):
        args = Namespace(
            data_dir=str(self.data_dir),
            key=None,
            id="Q1",
            location=None,
            title=None,
            status="curated",
            reason="主干节点",
            reviewed_by=None,
            sync_curation=True,
            sync_allowlist=False,
            priority_bonus=24,
        )

        self.assertEqual(self.run_quietly(review_decision.command_mark, args), 0)
        curation = self.read_curation()
        entry = curation["focused_node_ids"]["Q1"]

        self.assertEqual(entry["reason"], "主干节点")
        self.assertEqual(entry["priority_bonus"], 24)
        self.assertEqual(entry["review_key"], "id:Q1")

    def test_mark_curated_can_sync_curation_by_title(self):
        args = Namespace(
            data_dir=str(self.data_dir),
            key=None,
            id=None,
            location=None,
            title="人工节点",
            status="curated",
            reason="人工维护",
            reviewed_by=None,
            sync_curation=True,
            sync_allowlist=False,
            priority_bonus=None,
        )

        self.assertEqual(self.run_quietly(review_decision.command_mark, args), 0)
        curation = self.read_curation()

        self.assertEqual(curation["focused_titles"]["人工节点"]["reason"], "人工维护")

    def test_mark_allowlisted_can_sync_duplicate_allowlist(self):
        args = Namespace(
            data_dir=str(self.data_dir),
            key="id:Q79925",
            id=None,
            location=None,
            title=None,
            status="allowlisted",
            reason="合法多路径",
            reviewed_by=None,
            sync_curation=False,
            sync_allowlist=True,
            priority_bonus=None,
        )

        self.assertEqual(self.run_quietly(review_decision.command_mark, args), 0)
        allowlist = self.read_allowlist()
        entry = allowlist["duplicate_ids"]["Q79925"]

        self.assertEqual(entry["reason"], "合法多路径")
        self.assertEqual(entry["review_key"], "id:Q79925")

    def test_sync_options_validate_status_and_key_type(self):
        with self.assertRaises(SystemExit):
            self.run_quietly(
                review_decision.command_mark,
                Namespace(
                    data_dir=str(self.data_dir),
                    key="location:root.json.children[0]",
                    id=None,
                    location=None,
                    title=None,
                    status="curated",
                    reason="无法同步",
                    reviewed_by=None,
                    sync_curation=True,
                    sync_allowlist=False,
                    priority_bonus=None,
                ),
            )

        with self.assertRaises(SystemExit):
            self.run_quietly(
                review_decision.command_mark,
                Namespace(
                    data_dir=str(self.data_dir),
                    key="id:Q1",
                    id=None,
                    location=None,
                    title=None,
                    status="confirmed",
                    reason="状态不匹配",
                    reviewed_by=None,
                    sync_curation=True,
                    sync_allowlist=False,
                    priority_bonus=None,
                ),
            )

    def test_remove_deletes_decision(self):
        self.run_quietly(
            review_decision.command_mark,
            Namespace(
                data_dir=str(self.data_dir),
                key="location:root.json.children[0]",
                id=None,
                location=None,
                title=None,
                status="deferred",
                reason="稍后处理",
                reviewed_by=None,
                sync_curation=False,
                sync_allowlist=False,
                priority_bonus=None,
            ),
        )

        self.assertEqual(
            self.run_quietly(
                review_decision.command_remove,
                Namespace(
                    data_dir=str(self.data_dir),
                    key="location:root.json.children[0]",
                    id=None,
                    location=None,
                    title=None,
                ),
            ),
            0,
        )
        data = self.read_decisions()

        self.assertEqual(data["decisions"], {})

    def test_list_can_filter_by_status(self):
        entries = [
            ("id:Q1", "confirmed", "已确认"),
            ("id:Q2", "deferred", "稍后"),
            ("id:Q3", "allowlisted", "合法重复"),
        ]
        for key, status, reason in entries:
            self.run_quietly(
                review_decision.command_mark,
                Namespace(
                    data_dir=str(self.data_dir),
                    key=key,
                    id=None,
                    location=None,
                    title=None,
                    status=status,
                    reason=reason,
                    reviewed_by=None,
                    sync_curation=False,
                    sync_allowlist=False,
                    priority_bonus=None,
                ),
            )

        result, output = self.capture_output(
            review_decision.command_list,
            Namespace(data_dir=str(self.data_dir), status=["deferred"]),
        )

        self.assertEqual(result, 0)
        self.assertIn("id:Q2", output)
        self.assertNotIn("id:Q1", output)
        self.assertNotIn("id:Q3", output)

    def test_make_key_requires_exactly_one_key_input(self):
        with self.assertRaises(SystemExit):
            review_decision.make_key(
                Namespace(key=None, id=None, location=None, title=None)
            )
        with self.assertRaises(SystemExit):
            review_decision.make_key(
                Namespace(key="id:Q1", id="Q1", location=None, title=None)
            )


if __name__ == "__main__":
    unittest.main()
