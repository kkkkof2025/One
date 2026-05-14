import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


DEFAULT_DATA_DIR = Path("data")
REVIEW_DECISIONS_FILE = "review_decisions.json"
CURATION_FILE = "curation.json"
VALIDATION_ALLOWLIST_FILE = "validation_allowlist.json"
VALID_STATUSES = ("confirmed", "curated", "allowlisted", "ignored", "deferred")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


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


def ensure_shape(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data.get("decisions"), dict):
        data["decisions"] = {}
    if "notes" not in data:
        data["notes"] = (
            "复核处理记录用于让 review_queue 过滤已经确认、暂缓、"
            "加入人工关注或加入允许列表的节点。key 通常来自 review_queue.json 的 review_key。"
        )
    return data


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


def ensure_allowlist_shape(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data.get("duplicate_ids"), dict):
        data["duplicate_ids"] = {}
    return data


def decision_path(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / REVIEW_DECISIONS_FILE


def curation_path(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / CURATION_FILE


def allowlist_path(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / VALIDATION_ALLOWLIST_FILE


def is_qid(value: str) -> bool:
    return bool(re.fullmatch(r"Q\d+", value or ""))


def split_key(key: str) -> Tuple[str, str]:
    if ":" not in key:
        return "", key
    prefix, value = key.split(":", 1)
    return prefix, value


def make_key(args: argparse.Namespace) -> str:
    values = [bool(args.key), bool(args.id), bool(args.location), bool(args.title)]
    if sum(values) != 1:
        raise SystemExit("必须且只能提供 --key、--id、--location 或 --title 之一")
    if args.key:
        return args.key
    if args.id:
        return f"id:{args.id}"
    if args.location:
        return f"location:{args.location}"
    return f"title:{args.title}"


def qid_from_key(key: str) -> Optional[str]:
    prefix, value = split_key(key)
    return value if prefix == "id" and is_qid(value) else None


def title_from_key(key: str) -> Optional[str]:
    prefix, value = split_key(key)
    return value if prefix == "title" and value.strip() else None


def validate_sync_options(args: argparse.Namespace, key: str) -> None:
    sync_curation = getattr(args, "sync_curation", False)
    sync_allowlist = getattr(args, "sync_allowlist", False)
    if sync_curation and args.status != "curated":
        raise SystemExit("--sync-curation 只能配合 --status curated 使用")
    if sync_allowlist and args.status != "allowlisted":
        raise SystemExit("--sync-allowlist 只能配合 --status allowlisted 使用")
    if sync_curation and not (qid_from_key(key) or title_from_key(key)):
        raise SystemExit("--sync-curation 需要 id:<QID> 或 title:<标题> 类型的 key")
    if sync_allowlist and not qid_from_key(key):
        raise SystemExit("--sync-allowlist 需要 id:<QID> 类型的 key")


def sync_curation(args: argparse.Namespace, key: str, updated_at: str) -> str:
    node_id = qid_from_key(key)
    title = title_from_key(key)
    path = curation_path(args)
    data = ensure_curation_shape(load_json(path))
    entry: Dict[str, Any] = {
        "reason": args.reason,
        "review_key": key,
        "updated_at": updated_at,
    }
    priority_bonus = getattr(args, "priority_bonus", None)
    if priority_bonus is not None:
        entry["priority_bonus"] = priority_bonus

    if node_id:
        data["focused_node_ids"][node_id] = entry
        label = node_id
    else:
        data["focused_titles"][title] = entry
        label = str(title)

    save_json(path, data)
    return label


def sync_allowlist(args: argparse.Namespace, key: str, updated_at: str) -> str:
    node_id = qid_from_key(key)
    if not node_id:
        raise SystemExit("--sync-allowlist 需要 id:<QID> 类型的 key")

    path = allowlist_path(args)
    data = ensure_allowlist_shape(load_json(path))
    data["duplicate_ids"][node_id] = {
        "reason": args.reason,
        "review_key": key,
        "updated_at": updated_at,
    }
    save_json(path, data)
    return node_id


def command_mark(args: argparse.Namespace) -> int:
    path = decision_path(args)
    data = ensure_shape(load_json(path))
    key = make_key(args)
    validate_sync_options(args, key)
    updated_at = now_utc()
    data["decisions"][key] = {
        "status": args.status,
        "reason": args.reason,
        "updated_at": updated_at,
    }
    if args.reviewed_by:
        data["decisions"][key]["reviewed_by"] = args.reviewed_by
    save_json(path, data)
    if getattr(args, "sync_curation", False):
        label = sync_curation(args, key, updated_at)
        print(f"已同步人工关注: {label}")
    if getattr(args, "sync_allowlist", False):
        label = sync_allowlist(args, key, updated_at)
        print(f"已同步重复 ID 允许列表: {label}")
    print(f"已记录复核处理: {key} -> {args.status}")
    return 0


def command_remove(args: argparse.Namespace) -> int:
    path = decision_path(args)
    data = ensure_shape(load_json(path))
    key = make_key(args)
    removed = data["decisions"].pop(key, None)
    save_json(path, data)
    if removed is None:
        print(f"未找到复核处理: {key}")
    else:
        print(f"已移除复核处理: {key}")
    return 0


def command_list(args: argparse.Namespace) -> int:
    data = ensure_shape(load_json(decision_path(args)))
    decisions = data.get("decisions", {})
    statuses = set(getattr(args, "status", []) or [])
    keys = []
    for key in sorted(decisions):
        entry = decisions[key]
        if statuses and (
            not isinstance(entry, dict) or entry.get("status") not in statuses
        ):
            continue
        keys.append(key)

    if not keys:
        print("<empty>")
        return 0
    for key in keys:
        entry = decisions[key]
        if not isinstance(entry, dict):
            print(f"{key}: <格式异常>")
            continue
        parts = [
            key,
            str(entry.get("status", "")),
            str(entry.get("reason", "")),
        ]
        if entry.get("reviewed_by"):
            parts.append(f"reviewed_by={entry['reviewed_by']}")
        print(" | ".join(part for part in parts if part))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain review queue decisions.")
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Path to the data directory. Default: data",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    mark = subparsers.add_parser("mark", help="Record a review decision.")
    add_key_arguments(mark)
    mark.add_argument("--status", required=True, choices=VALID_STATUSES)
    mark.add_argument("--reason", required=True)
    mark.add_argument("--reviewed-by")
    mark.add_argument(
        "--sync-curation",
        action="store_true",
        help="When status is curated, also add the id/title to curation.json.",
    )
    mark.add_argument(
        "--sync-allowlist",
        action="store_true",
        help=(
            "When status is allowlisted, also add the QID to "
            "validation_allowlist.json duplicate_ids."
        ),
    )
    mark.add_argument(
        "--priority-bonus",
        type=int,
        help="Optional priority bonus written with --sync-curation.",
    )
    mark.set_defaults(func=command_mark)

    remove = subparsers.add_parser("remove", help="Remove a review decision.")
    add_key_arguments(remove)
    remove.set_defaults(func=command_remove)

    list_command = subparsers.add_parser("list", help="List review decisions.")
    list_command.add_argument(
        "--status",
        action="append",
        choices=VALID_STATUSES,
        help="Only list decisions with this status. Can be used more than once.",
    )
    list_command.set_defaults(func=command_list)
    return parser


def add_key_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--key", help="Exact review_key from review_queue.json.")
    parser.add_argument("--id", help="Wikidata QID, stored as id:<QID>.")
    parser.add_argument("--location", help="Data location, stored as location:<path>.")
    parser.add_argument("--title", help="Title key, stored as title:<title>.")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
