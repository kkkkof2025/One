import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_DATA_DIR = Path("data")
CURATION_FILE_NAME = "curation.json"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def ensure_curation_shape(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data.get("focused_node_ids"), dict):
        data["focused_node_ids"] = {}
    if not isinstance(data.get("focused_titles"), dict):
        data["focused_titles"] = {}
    if "notes" not in data:
        data["notes"] = (
            "人工关注节点会提升质量评分和默认扩展优先级；"
            "仍可在单个节点上使用 expansion_priority 做更强的人工覆盖。"
        )
    return data


def qid(value: str) -> str:
    if not re.fullmatch(r"Q\d+", value or ""):
        raise argparse.ArgumentTypeError("必须是 Wikidata QID，例如 Q1")
    return value


def curation_path(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / CURATION_FILE_NAME


def focus_entry(reason: str, priority_bonus: Optional[int]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"reason": reason}
    if priority_bonus is not None:
        entry["priority_bonus"] = priority_bonus
    return entry


def command_focus(args: argparse.Namespace) -> int:
    if not args.id and not args.title:
        raise SystemExit("必须提供 --id 或 --title")
    if args.id and args.title:
        raise SystemExit("--id 和 --title 只能选一个")

    path = curation_path(args)
    data = ensure_curation_shape(load_json(path))
    entry = focus_entry(args.reason, args.priority_bonus)

    if args.id:
        data["focused_node_ids"][args.id] = entry
        label = args.id
    else:
        data["focused_titles"][args.title] = entry
        label = args.title

    save_json(path, data)
    print(f"已关注: {label}")
    return 0


def command_unfocus(args: argparse.Namespace) -> int:
    if not args.id and not args.title:
        raise SystemExit("必须提供 --id 或 --title")
    if args.id and args.title:
        raise SystemExit("--id 和 --title 只能选一个")

    path = curation_path(args)
    data = ensure_curation_shape(load_json(path))
    if args.id:
        removed = data["focused_node_ids"].pop(args.id, None)
        label = args.id
    else:
        removed = data["focused_titles"].pop(args.title, None)
        label = args.title

    save_json(path, data)
    if removed is None:
        print(f"未找到: {label}")
    else:
        print(f"已取消关注: {label}")
    return 0


def describe_entry(key: str, entry: Any) -> str:
    if isinstance(entry, str):
        return f"{key}: {entry}"
    if not isinstance(entry, dict):
        return f"{key}: <格式异常>"
    parts = [key, entry.get("reason", "")]
    if entry.get("priority_bonus") is not None:
        parts.append(f"priority_bonus={entry['priority_bonus']}")
    if entry.get("enabled") is False:
        parts.append("disabled")
    return " | ".join(str(part) for part in parts if part != "")


def command_list(args: argparse.Namespace) -> int:
    path = curation_path(args)
    data = ensure_curation_shape(load_json(path))
    focused_ids = data.get("focused_node_ids", {})
    focused_titles = data.get("focused_titles", {})

    print("focused_node_ids:")
    if focused_ids:
        for key in sorted(focused_ids):
            print(f"- {describe_entry(key, focused_ids[key])}")
    else:
        print("- <empty>")

    print("focused_titles:")
    if focused_titles:
        for key in sorted(focused_titles):
            print(f"- {describe_entry(key, focused_titles[key])}")
    else:
        print("- <empty>")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain One curation focus nodes.")
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Path to the data directory. Default: data",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    focus = subparsers.add_parser("focus", help="Add or update a focused node.")
    focus.add_argument("--id", type=qid, help="Wikidata QID to focus, for example Q1.")
    focus.add_argument("--title", help="Manual title to focus when no QID exists.")
    focus.add_argument("--reason", required=True, help="Human reason for focusing it.")
    focus.add_argument("--priority-bonus", type=int, help="Optional priority bonus.")
    focus.set_defaults(func=command_focus)

    unfocus = subparsers.add_parser("unfocus", help="Remove a focused node.")
    unfocus.add_argument("--id", type=qid, help="Wikidata QID to remove.")
    unfocus.add_argument("--title", help="Manual title to remove.")
    unfocus.set_defaults(func=command_unfocus)

    list_command = subparsers.add_parser("list", help="List focused nodes.")
    list_command.set_defaults(func=command_list)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
