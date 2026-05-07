import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from SPARQLWrapper import JSON, SPARQLWrapper


DATA_DIR = Path("data")
NODES_DIR = DATA_DIR / "nodes"
ROOT_FILE = DATA_DIR / "root.json"
STATS_FILE = DATA_DIR / "stats.json"
GROWTH_HISTORY_FILE = DATA_DIR / "growth_history.json"

QUERY_LIMIT = int(os.environ.get("ONE_QUERY_LIMIT", "50"))
MAX_REQUESTS = int(os.environ.get("ONE_MAX_REQUESTS", "20"))
REQUEST_DELAY = float(os.environ.get("ONE_REQUEST_DELAY", "1.0"))
HISTORY_LIMIT = int(os.environ.get("ONE_GROWTH_HISTORY_LIMIT", "365"))
WIKIDATA_ENDPOINT = os.environ.get(
    "ONE_WIKIDATA_ENDPOINT", "https://query.wikidata.org/sparql"
)
USER_AGENT = os.environ.get(
    "ONE_USER_AGENT", "OneKnowledgeTree/0.2 (scheduled GitHub Actions)"
)

VALID_STATUSES = {"pending", "loaded", "error", "manual"}
FETCH_STRATEGY_VERSION = 2
request_count = 0
nodes_added_this_run = 0


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_json_array(path: Path) -> List[Any]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def is_qid(value: Any) -> bool:
    return bool(re.fullmatch(r"Q\d+", str(value or "")))


def safe_slug(text: Any, fallback: str = "node") -> str:
    slug = re.sub(r'[\\/*?:"<>|]', "", str(text or "")).strip()
    slug = re.sub(r"\s+", "-", slug)
    return (slug[:80] or fallback).strip(".")


def node_file_for(node: Dict[str, Any]) -> Path:
    node_id = str(node.get("id", "")).strip()
    if is_qid(node_id):
        return NODES_DIR / f"{node_id}.json"
    return NODES_DIR / f"{safe_slug(node.get('title'))}.json"


def data_relative_path(path: Path) -> str:
    return path.relative_to(DATA_DIR).as_posix()


def child_key(node: Dict[str, Any]) -> str:
    node_id = str(node.get("id", "")).strip()
    if node_id:
        return f"id:{node_id}"
    return f"title:{node.get('title', '')}"


def node_identity(node: Dict[str, Any], path: Optional[Path] = None) -> str:
    if path is not None:
        return f"path:{path.resolve().as_posix()}"
    node_id = str(node.get("id", "")).strip()
    if node_id:
        return f"id:{node_id}"
    return f"title:{str(node.get('title', '未命名')).strip()}"


def normalize_node(node: Dict[str, Any]) -> bool:
    changed = False

    if "title" not in node:
        node["title"] = "未命名"
        changed = True

    if "children" not in node or not isinstance(node["children"], list):
        node["children"] = []
        changed = True

    if "fetch_done" in node:
        node["children_status"] = "loaded" if node.pop("fetch_done") else "pending"
        changed = True

    if node.get("children_status") not in VALID_STATUSES:
        node["children_status"] = "loaded" if node["children"] else "pending"
        changed = True

    if node["children_status"] == "loaded" and not node["children"]:
        if node.get("is_leaf") is not True:
            node["is_leaf"] = True
            changed = True
    elif node.get("is_leaf") is True:
        node["is_leaf"] = False
        changed = True

    return changed


def pointer_from_node(node: Dict[str, Any], path: Path) -> Dict[str, Any]:
    pointer: Dict[str, Any] = {
        "title": node.get("title", "未命名"),
        "data_source": data_relative_path(path),
        "children_status": node.get("children_status", "pending"),
        "is_leaf": bool(node.get("is_leaf", False)),
    }
    if node.get("id"):
        pointer["id"] = node["id"]
    if node.get("fetch_strategy_version"):
        pointer["fetch_strategy_version"] = node["fetch_strategy_version"]
    return pointer


def sparql_literal(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def build_wikidata_query(node: Dict[str, Any]) -> Optional[str]:
    node_id = str(node.get("id", "")).strip()
    title = str(node.get("title", "")).strip()

    if is_qid(node_id):
        return f"""
SELECT DISTINCT ?item ?itemLabel ?relation WHERE {{
  {{
    ?item wdt:P279 wd:{node_id} .
    BIND("subclass" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P31 wd:{node_id} .
    BIND("instance" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P361 wd:{node_id} .
    BIND("part_of" AS ?relation)
  }}
  UNION
  {{
    wd:{node_id} wdt:P527 ?item .
    BIND("has_part" AS ?relation)
  }}
  UNION
  {{
    wd:{node_id} wdt:P2670 ?item .
    BIND("has_parts_of_class" AS ?relation)
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "zh". }}
}}
ORDER BY ?relation ?itemLabel
LIMIT {QUERY_LIMIT}
"""

    if title:
        return f"""
SELECT DISTINCT ?item ?itemLabel ?relation WHERE {{
  ?parent rdfs:label {sparql_literal(title)}@zh .
  {{
    ?item wdt:P279 ?parent .
    BIND("subclass" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P31 ?parent .
    BIND("instance" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P361 ?parent .
    BIND("part_of" AS ?relation)
  }}
  UNION
  {{
    ?parent wdt:P527 ?item .
    BIND("has_part" AS ?relation)
  }}
  UNION
  {{
    ?parent wdt:P2670 ?item .
    BIND("has_parts_of_class" AS ?relation)
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "zh". }}
}}
ORDER BY ?relation ?itemLabel
LIMIT {QUERY_LIMIT}
"""

    return None


def fetch_wikidata_children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = build_wikidata_query(node)
    if not query:
        return []

    sparql = SPARQLWrapper(WIKIDATA_ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.addCustomHttpHeader("User-Agent", USER_AGENT)
    sparql.setQuery(query)

    results = sparql.query().convert()
    children: List[Dict[str, Any]] = []
    seen = set()

    for result in results.get("results", {}).get("bindings", []):
        item = result.get("item", {}).get("value", "")
        node_id = item.rsplit("/", 1)[-1] if item else ""
        label = result.get("itemLabel", {}).get("value", "").strip()

        if not label or label == node.get("title"):
            continue
        if label.startswith("Q") and label[1:].isdigit():
            continue

        key = node_id or label
        if key in seen:
            continue
        seen.add(key)

        child: Dict[str, Any] = {
            "title": label,
            "children_status": "pending",
            "is_leaf": False,
        }
        if is_qid(node_id):
            child["id"] = node_id
        relation = result.get("relation", {}).get("value", "").strip()
        if relation:
            child["source_relation"] = relation
        children.append(child)

    return children


def merge_children(
    existing: List[Dict[str, Any]], fetched: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int]:
    merged: List[Dict[str, Any]] = []
    positions: Dict[str, Dict[str, Any]] = {}
    added = 0

    for child in existing:
        if not isinstance(child, dict):
            continue
        normalize_node(child)
        merged.append(child)
        positions[child_key(child)] = child

    for child in fetched:
        key = child_key(child)
        current = positions.get(key)
        if current is None:
            merged.append(child)
            positions[key] = child
            added += 1
            continue

        for field in ("id", "title", "source_relation"):
            if child.get(field) and current.get(field) != child[field]:
                current[field] = child[field]

    return merged, added


def materialize_child(child: Dict[str, Any]) -> Tuple[Dict[str, Any], Path, bool]:
    changed = False

    if child.get("data_source"):
        path = DATA_DIR / str(child["data_source"])
        child_data = load_json(path)
        if child_data is None:
            child_data = {
                "id": child.get("id"),
                "title": child.get("title", "未命名"),
                "children_status": child.get("children_status", "pending"),
                "children": child.get("children", []),
            }
            normalize_node(child_data)
            save_json(path, child_data)
            changed = True
        return child_data, path, changed

    path = node_file_for(child)
    child_data = load_json(path)
    if child_data is None:
        child_data = {
            "id": child.get("id"),
            "title": child.get("title", "未命名"),
            "children_status": child.get("children_status", "pending"),
            "children": child.get("children", []),
        }
        normalize_node(child_data)
        save_json(path, child_data)
        changed = True

    pointer = pointer_from_node(child_data, path)
    if child != pointer:
        child.clear()
        child.update(pointer)
        changed = True

    return child_data, path, changed


def should_fetch(node: Dict[str, Any]) -> bool:
    if node.get("id") == "root":
        return False

    if build_wikidata_query(node) is None:
        return False

    status = node.get("children_status")
    if status in {"pending", "error"} and not node.get("is_leaf"):
        return True

    strategy_version = int(node.get("fetch_strategy_version", 0) or 0)
    return status == "loaded" and strategy_version < FETCH_STRATEGY_VERSION


def process_node_data(data: Dict[str, Any], file_path: Path) -> bool:
    global request_count, nodes_added_this_run

    changed = normalize_node(data)

    if request_count < MAX_REQUESTS and should_fetch(data):
        request_count += 1
        print(f"[{request_count}/{MAX_REQUESTS}] 查询: {data.get('title')}")
        try:
            fetched_children = fetch_wikidata_children(data)
            data["children"], added = merge_children(data["children"], fetched_children)
            nodes_added_this_run += added
            data["children_status"] = "loaded"
            data["fetch_strategy_version"] = FETCH_STRATEGY_VERSION
            data["updated_at"] = now_utc()
            data.pop("last_error", None)
            data["is_leaf"] = len(data["children"]) == 0
            changed = True
            print(f"  新增节点: {added}，当前子类: {len(data['children'])}")
        except Exception as exc:
            data["children_status"] = "error"
            data["last_error"] = str(exc)
            data["updated_at"] = now_utc()
            changed = True
            print(f"  查询失败: {exc}")

        if REQUEST_DELAY > 0:
            time.sleep(REQUEST_DELAY)

    for child in list(data.get("children", [])):
        if request_count >= MAX_REQUESTS:
            break
        if not isinstance(child, dict):
            continue
        child_strategy_version = int(child.get("fetch_strategy_version", 0) or 0)
        if child.get("is_leaf") is True and child_strategy_version >= FETCH_STRATEGY_VERSION:
            continue

        child_data, child_path, pointer_changed = materialize_child(child)
        changed = changed or pointer_changed

        child_changed = process_node_data(child_data, child_path)
        if child_changed:
            save_json(child_path, child_data)
            changed = True

        pointer = pointer_from_node(child_data, child_path)
        if child != pointer:
            child.clear()
            child.update(pointer)
            changed = True

    return changed


def count_tree_nodes(node: Dict[str, Any], path: Optional[Path] = None, visited=None) -> int:
    if visited is None:
        visited = set()

    identity = node_identity(node, path)
    if identity in visited:
        return 0
    visited.add(identity)

    total = 1
    for child in node.get("children", []):
        if not isinstance(child, dict):
            continue

        child_path = None
        child_node = child
        if child.get("data_source"):
            child_path = DATA_DIR / str(child["data_source"])
            loaded = load_json(child_path)
            if loaded is not None:
                child_node = loaded

        total += count_tree_nodes(child_node, child_path, visited)

    return total


def record_growth_history(total_nodes: int) -> None:
    history = load_json_array(GROWTH_HISTORY_FILE)
    entry = {
        "run_at": now_utc(),
        "added_nodes": nodes_added_this_run,
        "total_nodes": total_nodes,
    }
    history.append(entry)

    if HISTORY_LIMIT > 0 and len(history) > HISTORY_LIMIT:
        history = history[-HISTORY_LIMIT:]

    save_json(GROWTH_HISTORY_FILE, history)
    save_json(
        STATS_FILE,
        {
            "generated_at": entry["run_at"],
            "total_nodes": total_nodes,
            "last_added_nodes": nodes_added_this_run,
            "history_entries": len(history),
            "history_file": GROWTH_HISTORY_FILE.relative_to(DATA_DIR).as_posix(),
        },
    )


def default_root() -> Dict[str, Any]:
    return {
        "id": "root",
        "title": "万物",
        "children_status": "loaded",
        "children": [
            {
                "id": "Q1",
                "title": "宇宙",
                "data_source": "nodes/Q1.json",
                "children_status": "pending",
                "is_leaf": False,
            },
            {
                "id": "Q3",
                "title": "生命",
                "data_source": "nodes/Q3.json",
                "children_status": "pending",
                "is_leaf": False,
            },
        ],
    }


def bootstrap_root_files(root: Dict[str, Any]) -> bool:
    changed = False
    for child in root.get("children", []):
        if not isinstance(child, dict):
            continue
        _, _, pointer_changed = materialize_child(child)
        changed = changed or pointer_changed
    return changed


def main() -> None:
    global nodes_added_this_run
    root_data = load_json(ROOT_FILE)
    if root_data is None:
        root_data = default_root()

    changed = normalize_node(root_data)
    changed = bootstrap_root_files(root_data) or changed
    changed = process_node_data(root_data, ROOT_FILE) or changed

    if changed:
        save_json(ROOT_FILE, root_data)
        print("根节点数据已更新。")
    else:
        print("没有发现需要保存的数据变化。")

    total_nodes = count_tree_nodes(root_data, ROOT_FILE)
    record_growth_history(total_nodes)
    print(f"本次新增节点数: {nodes_added_this_run}")
    print(f"当前总节点数: {total_nodes}")
    print(f"本次 Wikidata 请求数: {request_count}/{MAX_REQUESTS}")


if __name__ == "__main__":
    main()
