import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Set

import wikipediaapi


SOURCE_FILE = Path("万物.txt")
OUTPUT_DIR = Path("output/wiki_categories")
MAX_FILE_SIZE_MB = float(os.environ.get("ONE_WIKI_SPLIT_THRESHOLD_MB", "2"))
MAX_DEPTH = int(os.environ.get("ONE_WIKI_MAX_DEPTH", "2"))
MAX_BRANCHES_PER_NODE = int(os.environ.get("ONE_WIKI_MAX_BRANCHES", "20"))
REQUEST_DELAY = float(os.environ.get("ONE_WIKI_REQUEST_DELAY", "1.0"))
USER_AGENT = os.environ.get(
    "ONE_USER_AGENT", "OneKnowledgeTree/0.2 (local category expansion)"
)


def create_wiki_client() -> wikipediaapi.Wikipedia:
    try:
        return wikipediaapi.Wikipedia(language="zh", user_agent=USER_AGENT)
    except TypeError:
        return wikipediaapi.Wikipedia("zh")


wiki = create_wiki_client()


def safe_name(title: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    name = re.sub(r"\s+", "-", name)
    return name[:80] or "category"


def load_seed_categories(path: Path) -> List[str]:
    categories: List[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith(" ") or raw_line.strip().startswith("- "):
            continue
        title = raw_line.strip().rstrip(":：")
        if title:
            categories.append(title)
    return categories


def fetch_subcategories(category: str) -> List[str]:
    page = wiki.page(f"Category:{category}")
    if not page.exists():
        return []

    children: List[str] = []
    for member in page.categorymembers.values():
        if member.ns == wikipediaapi.Namespace.CATEGORY:
            children.append(member.title.replace("Category:", "", 1))

    return sorted(set(children))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_sharded(category: str, node: Dict[str, Any], output_dir: Path) -> None:
    payload = json.dumps(node, ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) / 1024 / 1024 <= MAX_FILE_SIZE_MB:
        save_json(output_dir / f"{safe_name(category)}.json", node)
        return

    children = node.get("children", [])
    shard_size = 50
    for index in range(0, len(children), shard_size):
        shard = {
            "title": node["title"],
            "part": index // shard_size + 1,
            "children": children[index : index + shard_size],
        }
        save_json(output_dir / f"{safe_name(category)}_part{index // shard_size + 1}.json", shard)


def process_category(category: str, depth: int, output_dir: Path, visited: Set[str]) -> None:
    if depth > MAX_DEPTH or category in visited:
        return
    visited.add(category)

    print(f"查询分类: {category}")
    subcategories = fetch_subcategories(category)
    node = {
        "title": category,
        "children": [{"title": child, "children_status": "pending"} for child in subcategories],
    }
    save_sharded(category, node, output_dir)

    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)

    for child in subcategories[:MAX_BRANCHES_PER_NODE]:
        process_category(child, depth + 1, output_dir / safe_name(category), visited)


def main() -> None:
    categories = load_seed_categories(SOURCE_FILE)
    if not categories:
        raise RuntimeError(f"没有从 {SOURCE_FILE} 找到可扩展的顶层分类。")

    visited: Set[str] = set()
    for category in categories:
        process_category(category, 1, OUTPUT_DIR, visited)

    print(f"维基百科分类数据已保存到: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
