import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from argparse import Namespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CURATE_NODE_PATH = REPO_ROOT / "scripts" / "curate_node.py"
spec = importlib.util.spec_from_file_location("curate_node", CURATE_NODE_PATH)
curate_node = importlib.util.module_from_spec(spec)
sys.modules["curate_node"] = curate_node
spec.loader.exec_module(curate_node)


class CurateNodeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"

    def tearDown(self):
        self.temp_dir.cleanup()

    def read_curation(self):
        with (self.data_dir / "curation.json").open("r", encoding="utf-8") as f:
            return json.load(f)

    def run_quietly(self, func, args):
        with redirect_stdout(io.StringIO()):
            return func(args)

    def test_focus_adds_qid_entry(self):
        args = Namespace(
            data_dir=str(self.data_dir),
            id="Q1",
            title=None,
            reason="主干节点",
            priority_bonus=24,
        )

        self.assertEqual(self.run_quietly(curate_node.command_focus, args), 0)
        data = self.read_curation()

        self.assertEqual(data["focused_node_ids"]["Q1"]["reason"], "主干节点")
        self.assertEqual(data["focused_node_ids"]["Q1"]["priority_bonus"], 24)
        self.assertIn("focused_titles", data)

    def test_focus_adds_title_entry(self):
        args = Namespace(
            data_dir=str(self.data_dir),
            id=None,
            title="人工节点",
            reason="人工策展",
            priority_bonus=None,
        )

        self.assertEqual(self.run_quietly(curate_node.command_focus, args), 0)
        data = self.read_curation()

        self.assertEqual(data["focused_titles"]["人工节点"]["reason"], "人工策展")
        self.assertNotIn("priority_bonus", data["focused_titles"]["人工节点"])

    def test_unfocus_removes_entry(self):
        self.run_quietly(
            curate_node.command_focus,
            Namespace(
                data_dir=str(self.data_dir),
                id="Q1",
                title=None,
                reason="主干节点",
                priority_bonus=None,
            )
        )

        self.assertEqual(
            self.run_quietly(
                curate_node.command_unfocus,
                Namespace(data_dir=str(self.data_dir), id="Q1", title=None)
            ),
            0,
        )
        data = self.read_curation()

        self.assertNotIn("Q1", data["focused_node_ids"])

    def test_qid_type_rejects_non_qid(self):
        with self.assertRaises(Exception):
            curate_node.qid("not-qid")


if __name__ == "__main__":
    unittest.main()
