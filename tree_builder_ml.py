import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


SOURCE_FILE = Path("万物.txt")
OUTPUT_DIR = Path("output")
INITIAL_THRESHOLD_MB = float(os.environ.get("ONE_SPLIT_THRESHOLD_MB", "2"))


def parse_outline(file_path: Path) -> Dict[str, Any]:
    root: Dict[str, Any] = {"title": "万物知识结构", "children": []}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        text = raw_line.strip()
        if text.startswith("- "):
            text = text[2:].strip()

        title, inline_children = split_title_and_inline_children(text)
        if not title:
            continue

        node: Dict[str, Any] = {"title": title, "children": []}
        node["children"].extend({"title": child, "children": []} for child in inline_children)

        while stack and indent <= stack[-1][0]:
            stack.pop()
        stack[-1][1]["children"].append(node)
        stack.append((indent, node))

    return root


def split_title_and_inline_children(text: str) -> Tuple[str, List[str]]:
    if ":" not in text and "：" not in text:
        return text.rstrip(":：").strip(), []

    separator = ":" if ":" in text else "："
    title, rest = text.split(separator, 1)
    children = [item.strip() for item in rest.replace("，", ",").split(",") if item.strip()]
    return title.strip(), children


def safe_name(title: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    name = re.sub(r"\s+", "-", name)
    return name[:80] or "node"


def size_mb(data: Dict[str, Any]) -> float:
    return len(json.dumps(data, ensure_ascii=False).encode("utf-8")) / 1024 / 1024


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_and_save(node: Dict[str, Any], output_dir: Path, threshold_mb: float) -> None:
    if size_mb(node) <= threshold_mb or not node.get("children"):
        save_json(output_dir / "data.json", node)
        return

    shallow = {"title": node["title"], "children": []}
    for child in node["children"]:
        child_dir = output_dir / safe_name(str(child.get("title", "node")))
        split_and_save(child, child_dir, threshold_mb)
        shallow["children"].append(
            {
                "title": child.get("title", "未命名"),
                "data_source": f"{safe_name(str(child.get('title', 'node')))}/data.json",
            }
        )

    save_json(output_dir / "data.json", shallow)


def main() -> None:
    tree = parse_outline(SOURCE_FILE)
    split_and_save(tree, OUTPUT_DIR / "outline_tree", INITIAL_THRESHOLD_MB)
    print(f"文本知识树已保存到: {OUTPUT_DIR / 'outline_tree'}")


if __name__ == "__main__":
    main()
