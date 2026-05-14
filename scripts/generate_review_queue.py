import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import grow_json  # noqa: E402


DEFAULT_DATA_DIR = Path("data")
REVIEW_QUEUE_FILE = "review_queue.json"
REVIEW_DECISIONS_FILE = "review_decisions.json"
DEFAULT_LIMIT = int(os.environ.get("ONE_REVIEW_QUEUE_LIMIT", "200"))
DEFAULT_THRESHOLD = int(
    os.environ.get("ONE_REVIEW_QUEUE_THRESHOLD", str(grow_json.QUALITY_REVIEW_THRESHOLD))
)
SUPPRESSING_DECISION_STATUSES = {
    "confirmed",
    "curated",
    "allowlisted",
    "ignored",
    "deferred",
}
REVIEW_REASON_PREFIXES = (
    "duplicate_id:",
    "disambiguation",
    "broad_title",
    "missing_title",
    "missing_id",
    "non_zh_label",
    "fetch_error",
)
REVIEW_REASON_CATEGORIES = (
    ("non_zh_label", "缺少中文标签"),
    ("duplicate_id", "重复 ID 风险"),
    ("error", "加载错误"),
    ("low_quality", "低质量分"),
    ("needs_review", "待人工复核"),
    ("missing_id", "缺少 Wikidata QID"),
    ("missing_title", "缺少标题"),
    ("disambiguation", "消歧义标题"),
    ("broad_title", "过泛标题"),
)
CHILDREN_STATUS_LABELS = {
    "pending": "待扩展",
    "loaded": "已加载",
    "error": "加载错误",
    "manual": "人工维护",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def configure_grow_json(data_dir: Path) -> None:
    grow_json.DATA_DIR = data_dir
    grow_json.NODES_DIR = data_dir / "nodes"
    grow_json.ROOT_FILE = data_dir / "root.json"
    grow_json.STATS_FILE = data_dir / "stats.json"
    grow_json.GROWTH_HISTORY_FILE = data_dir / "growth_history.json"
    grow_json.CURATION_FILE = data_dir / "curation.json"
    grow_json.VALIDATION_ALLOWLIST_FILE = data_dir / "validation_allowlist.json"
    grow_json.CURATION_CACHE = None


def title_path(path_nodes: List[Dict[str, Any]]) -> str:
    return " / ".join(str(node.get("title") or "未命名") for node in path_nodes)


def relative_location(data_dir: Path, path: Optional[Path], fallback: str) -> str:
    if path is None:
        return fallback
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def node_summary(node: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "title": node.get("title", "未命名"),
        "children_status": node.get("children_status", "pending"),
        "quality_score": metadata.get("quality_score"),
        "review_status": metadata.get("review_status"),
        "quality_reasons": metadata.get("quality_reasons", []),
    }
    for field in (
        "id",
        "data_source",
        "source_relation",
        "updated_at",
        "last_error",
        "fetch_strategy_version",
    ):
        if node.get(field) is not None:
            summary[field] = node[field]
    return summary


def review_key_for_item(item: Dict[str, Any]) -> str:
    node_id = str(item.get("id", "")).strip()
    if grow_json.is_qid(node_id):
        return f"id:{node_id}"
    location = str(item.get("location", "")).strip()
    if location:
        return f"location:{location}"
    path = str(item.get("path", "")).strip()
    title = str(item.get("title", "")).strip()
    return f"title:{path}/{title}"


def load_review_decisions(data_dir: Path) -> Dict[str, Dict[str, Any]]:
    data = load_json(data_dir / REVIEW_DECISIONS_FILE)
    if not isinstance(data, dict):
        return {}
    decisions = data.get("decisions", {})
    if not isinstance(decisions, dict):
        return {}
    return {
        str(key): value
        for key, value in decisions.items()
        if isinstance(value, dict)
    }


def decision_suppresses_item(decision: Optional[Dict[str, Any]]) -> bool:
    if not decision:
        return False
    return str(decision.get("status", "")).strip() in SUPPRESSING_DECISION_STATUSES


def is_review_candidate(
    node: Dict[str, Any], metadata: Dict[str, Any], threshold: int
) -> bool:
    reasons = metadata.get("quality_reasons", [])
    if metadata.get("review_status") == "needs_review":
        return True
    score = metadata.get("quality_score")
    if isinstance(score, (int, float)) and score <= threshold:
        return True
    if node.get("children_status") == "error" or node.get("last_error"):
        return True
    return any(
        reason == prefix or str(reason).startswith(prefix)
        for reason in reasons
        for prefix in REVIEW_REASON_PREFIXES
    )


def review_priority(node: Dict[str, Any], metadata: Dict[str, Any]) -> float:
    score = float(metadata.get("quality_score", 0) or 0)
    reasons = [str(reason) for reason in metadata.get("quality_reasons", [])]
    priority = 100 - score

    if metadata.get("review_status") == "needs_review":
        priority += 30
    if node.get("children_status") == "error" or node.get("last_error"):
        priority += 30
    if any(reason.startswith("duplicate_id:") for reason in reasons):
        priority += 24
    if "disambiguation" in reasons:
        priority += 22
    if "broad_title" in reasons:
        priority += 14
    if "missing_title" in reasons or "missing_id" in reasons:
        priority += 18
    if "non_zh_label" in reasons:
        priority += 10
    return round(priority, 2)


def suggested_action(node: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    reasons = [str(reason) for reason in metadata.get("quality_reasons", [])]
    if node.get("children_status") == "error" or node.get("last_error"):
        return "检查 last_error，必要时降低请求频率、重试或改为人工节点。"
    if any(reason.startswith("duplicate_id:") for reason in reasons):
        return "确认是否为合法多路径；合法则加入 validation_allowlist.json，否则合并或移除重复节点。"
    if "disambiguation" in reasons or "broad_title" in reasons:
        return "确认标题是否过泛或消歧义页，必要时替换为更具体的 Wikidata QID。"
    if "missing_title" in reasons or "non_zh_label" in reasons:
        return "补齐中文标题，或暂时标记为人工维护。"
    if "missing_id" in reasons:
        return "补充 Wikidata QID，或确认该节点应由人工维护。"
    return "复核分类位置、source_relation 和是否需要加入人工关注列表。"


def item_has_reason(item: Dict[str, Any], key: str) -> bool:
    reasons = [str(reason) for reason in item.get("quality_reasons", [])]
    return any(reason == key or reason.startswith(f"{key}:") for reason in reasons)


def item_in_reason_category(item: Dict[str, Any], category: str, threshold: int) -> bool:
    if category == "needs_review":
        return item.get("review_status") == "needs_review"
    if category == "low_quality":
        score = item.get("quality_score")
        return isinstance(score, (int, float)) and score <= threshold
    if category == "error":
        return (
            item.get("children_status") == "error"
            or bool(item.get("last_error"))
            or item_has_reason(item, "fetch_error")
        )
    return item_has_reason(item, category)


def build_reason_distribution(items: List[Dict[str, Any]], threshold: int) -> Dict[str, Any]:
    categories: List[Dict[str, Any]] = []
    for key, label in REVIEW_REASON_CATEGORIES:
        matched = [item for item in items if item_in_reason_category(item, key, threshold)]
        if not matched:
            continue
        categories.append(
            {
                "key": key,
                "label": label,
                "count": len(matched),
                "sample_review_keys": [
                    str(item.get("review_key", ""))
                    for item in matched[:5]
                    if item.get("review_key")
                ],
            }
        )

    raw_reasons: Dict[str, int] = {}
    for item in items:
        for reason in item.get("quality_reasons", []):
            key = str(reason)
            raw_reasons[key] = raw_reasons.get(key, 0) + 1

    raw_reason_counts = [
        {"reason": reason, "count": count}
        for reason, count in sorted(
            raw_reasons.items(),
            key=lambda entry: (-entry[1], entry[0]),
        )
    ]

    status_counts: Dict[str, int] = {}
    for item in items:
        status = str(item.get("children_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    status_summary = [
        {
            "status": status,
            "label": CHILDREN_STATUS_LABELS.get(status, status),
            "count": count,
        }
        for status, count in sorted(
            status_counts.items(),
            key=lambda entry: (-entry[1], entry[0]),
        )
    ]

    return {
        "total_items": len(items),
        "categories": categories,
        "raw_reasons": raw_reason_counts,
        "children_statuses": status_summary,
    }


def review_item(
    data_dir: Path,
    node: Dict[str, Any],
    path_nodes: List[Dict[str, Any]],
    location_path: Optional[Path],
    fallback_location: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    item = node_summary(node, metadata)
    item.update(
        {
            "path": title_path(path_nodes),
            "location": relative_location(data_dir, location_path, fallback_location),
            "priority": review_priority(node, metadata),
            "suggested_action": suggested_action(node, metadata),
        }
    )
    item["review_key"] = review_key_for_item(item)
    return item


def collect_review_items(
    data_dir: Path, root: Dict[str, Any], threshold: int
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    visited_files: Set[Path] = set()

    def visit(
        node: Any,
        path_nodes: List[Dict[str, Any]],
        location_path: Optional[Path],
        fallback_location: str,
    ) -> None:
        if not isinstance(node, dict):
            return

        if location_path is not None:
            resolved = location_path.resolve()
            if resolved in visited_files:
                return
            visited_files.add(resolved)

        data_source = node.get("data_source")
        if data_source:
            target_path = data_dir / str(data_source)
            target = load_json(target_path)
            if isinstance(target, dict):
                next_path = path_nodes[:-1] + [target] if path_nodes else [target]
                visit(target, next_path, target_path, str(data_source))
                return

        current_path = path_nodes if path_nodes and path_nodes[-1] is node else path_nodes + [node]
        metadata = grow_json.quality_metadata(node)
        if is_review_candidate(node, metadata, threshold):
            items.append(
                review_item(
                    data_dir,
                    node,
                    current_path,
                    location_path,
                    fallback_location,
                    metadata,
                )
            )

        for index, child in enumerate(node.get("children", [])):
            visit(
                child,
                current_path + [child] if isinstance(child, dict) else current_path,
                None,
                f"{fallback_location}.children[{index}]",
            )

    visit(root, [root], data_dir / "root.json", "root.json")
    return items


def generate_review_queue(
    data_dir: Path,
    limit: int = DEFAULT_LIMIT,
    threshold: int = DEFAULT_THRESHOLD,
) -> Dict[str, Any]:
    data_dir = data_dir.resolve()
    configure_grow_json(data_dir)
    root = load_json(data_dir / "root.json")
    if not isinstance(root, dict):
        raise ValueError("data/root.json must be a JSON object")

    grow_json.prepare_quality_context(root)
    decisions = load_review_decisions(data_dir)
    items = collect_review_items(data_dir, root, threshold)
    total_candidates = len(items)
    filtered_items = [
        item
        for item in items
        if not decision_suppresses_item(decisions.get(str(item.get("review_key", ""))))
    ]
    filtered_items.sort(
        key=lambda item: (
            -float(item.get("priority", 0) or 0),
            float(item.get("quality_score", 100) or 100),
            str(item.get("path", "")),
        )
    )

    if limit > 0:
        queue_items = filtered_items[:limit]
    else:
        queue_items = filtered_items

    return {
        "generated_at": now_utc(),
        "threshold": threshold,
        "limit": limit,
        "total_candidates": total_candidates,
        "suppressed_items": total_candidates - len(filtered_items),
        "decision_file": REVIEW_DECISIONS_FILE,
        "total_items": len(queue_items),
        "reason_distribution": build_reason_distribution(queue_items, threshold),
        "items": queue_items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate review queue for One data.")
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Path to the data directory. Default: data",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum number of review items. Default: {DEFAULT_LIMIT}",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"Quality score threshold. Default: {DEFAULT_THRESHOLD}",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    queue = generate_review_queue(data_dir, args.limit, args.threshold)
    save_json(data_dir / REVIEW_QUEUE_FILE, queue)
    print(f"已生成复核队列: {queue['total_items']} 项")
    categories = queue.get("reason_distribution", {}).get("categories", [])
    if categories:
        summary = "，".join(
            f"{category['label']} {category['count']}"
            for category in categories[:5]
        )
        print(f"原因分布: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
