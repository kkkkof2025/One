from html import escape
from pathlib import Path
from typing import Any, Dict, List, Tuple


SOURCE_FILE = Path("万物.txt")
OUTPUT_FILE = Path("output/knowledge_tree.html")


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
        node["children"].extend({"title": item, "children": []} for item in inline_children)

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


def render_node(node: Dict[str, Any]) -> str:
    children = node.get("children") or []
    label = escape(str(node.get("title", "未命名")))
    if not children:
        return f"<li>{label}</li>"

    child_html = "\n".join(render_node(child) for child in children)
    return f"<li>{label}\n<ul>\n{child_html}\n</ul>\n</li>"


def build_html(tree: Dict[str, Any]) -> str:
    body = "\n".join(render_node(child) for child in tree.get("children", []))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>万物知识结构</title>
  <style>
    body {{
      margin: 0;
      padding: 32px;
      color: #1f2933;
      background: #f7f8fa;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.6;
    }}
    main {{
      max-width: 880px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #d9dee7;
      border-radius: 8px;
      padding: 24px 28px;
    }}
    h1 {{
      margin: 0 0 18px;
      font-size: 24px;
    }}
    ul {{
      margin: 0 0 0 22px;
      padding: 0;
    }}
    li {{
      margin: 6px 0;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(str(tree.get("title", "万物知识结构")))}</h1>
    <ul>
{body}
    </ul>
  </main>
</body>
</html>
"""


def main() -> None:
    tree = parse_outline(SOURCE_FILE)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(build_html(tree), encoding="utf-8")
    print(f"HTML 文件已生成: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
