"""Run the markdown tree parser: python -m app.parser <file.md>"""

from app.parser.tree_parser import _default_manual_path, parse_markdown_file, print_tree
import argparse
import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Parse CT-200 manual markdown to a tree.")
    parser.add_argument(
        "markdown_file",
        nargs="?",
        default=str(_default_manual_path()),
        help="Path to markdown file (default: data/ct200_manual.md)",
    )
    parser.add_argument(
        "--show-body",
        action="store_true",
        help="Include truncated body snippets in tree output",
    )
    args = parser.parse_args()

    tree, irregularities = parse_markdown_file(args.markdown_file)

    print("=== Parsed Tree ===")
    print_tree(tree, show_body=args.show_body)
    print()
    print(f"=== Irregularities ({len(irregularities)}) ===")
    for index, item in enumerate(irregularities, start=1):
        location = f" @ {item.location}" if item.location else ""
        print(f"{index}. [{item.kind}]{location}")
        print(f"   Found: {item.description}")
        print(f"   Handling: {item.handling}")


if __name__ == "__main__":
    main()
