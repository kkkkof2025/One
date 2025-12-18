import os

SOURCE_FILE = "万物.txt"  # 输入文本文件
OUTPUT_FILE = "output/knowledge_tree.html"  # 生成的 HTML 文件


def parse_txt_to_html(file_path):
    """
    将层级文本文件转换为 HTML 格式
    """
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    html_content = ["<!DOCTYPE html>", "<html>", "<head>",
                    "<style>",
                    "body { font-family: Arial, sans-serif; line-height: 1.6; }",
                    "ul { list-style-type: none; margin-left: 20px; }",
                    "</style>",
                    "</head>",
                    "<body>",
                    "<h1>知识树展示</h1>",
                    "<ul>"]

    indent_levels = []  # 用于追踪缩进深度

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue  # 跳过空行

        # 计算当前行的缩进
        indent_level = len(line) - len(line.lstrip())
        if len(indent_levels) == 0 or indent_level > indent_levels[-1]:  # 如果缩进更深，开始一个新的 <ul>
            html_content.append("<ul>")
            indent_levels.append(indent_level)
        elif indent_level < indent_levels[-1]:  # 如果缩进减少，则需要关闭之前的 <ul>
            while indent_levels and indent_level < indent_levels[-1]:
                html_content.append("</ul>")
                indent_levels.pop()

        # 添加当前行到 HTML 内容
        html_content.append(f"<li>{stripped_line}</li>")

    # 闭合所有未结束的 <ul>
    while indent_levels:
        html_content.append("</ul>")
        indent_levels.pop()

    html_content.append("</ul>")
    html_content.append("</body>")
    html_content.append("</html>")

    return "\n".join(html_content)


def save_html(content, output_path):
    """
    将 HTML 内容写入文件
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"HTML 文件已生成: {output_path}")


def main():
    # 转换文本为 HTML
    html_content = parse_txt_to_html(SOURCE_FILE)
    # 保存 HTML 文件
    save_html(html_content, OUTPUT_FILE)


if __name__ == "__main__":
    main()