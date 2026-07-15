"""Parse CT-200 manual markdown into an in-memory section tree.

Numeric prefixes in heading text (e.g. 3.2, 2.1.1.1) are the source of truth
for hierarchy and sibling order — not markdown # depth and not file order.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
NUMERIC_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:\.\s+|\s+)(.*)$")
ROOT_LOGICAL_ID = "__root__"


@dataclass
class Irregularity:
    kind: str
    description: str
    handling: str
    location: str | None = None


@dataclass
class TreeNode:
    heading: str
    level: int
    path: str
    logical_id: str
    body: str
    content_hash: str
    order_index: int
    parent: TreeNode | None = None
    children: list[TreeNode] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = hash_body(self.body)


def hash_body(body: str) -> str:
    normalized = body.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def path_to_tuple(path: str) -> tuple[int, ...]:
    return tuple(int(part) for part in path.split("."))


def path_sort_key(path: str) -> tuple[int, ...]:
    return path_to_tuple(path)


def extract_numeric_heading(text: str) -> tuple[str, str, int] | None:
    """Return (path, title, level) when heading text starts with a numeric prefix."""
    match = NUMERIC_PREFIX_RE.match(text.strip())
    if not match:
        return None
    path = match.group(1)
    title = match.group(2).strip()
    level = len(path.split("."))
    return path, title, level


def find_parent_path(path: str, known_paths: set[str]) -> str | None:
    parts = path.split(".")
    for depth in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:depth])
        if candidate in known_paths:
            return candidate
    return None


@dataclass
class _SectionDraft:
    markdown_depth: int
    heading_line: str
    heading_text: str
    path: str | None
    title: str
    level: int
    body_lines: list[str] = field(default_factory=list)
    file_order: int = 0

    @property
    def body(self) -> str:
        return "\n".join(self.body_lines).strip()


def _split_sections(text: str) -> tuple[list[str], list[_SectionDraft], list[Irregularity]]:
    """Split markdown into preamble lines and heading-delimited sections."""
    irregularities: list[Irregularity] = []
    preamble: list[str] = []
    sections: list[_SectionDraft] = []
    current: _SectionDraft | None = None
    file_order = 0

    for raw_line in text.splitlines():
        heading_match = HEADING_RE.match(raw_line)
        if heading_match:
            if current is not None:
                sections.append(current)

            markdown_depth = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            numeric = extract_numeric_heading(heading_text)

            if numeric is None:
                path = None
                title = heading_text
                level = 0
            else:
                path, title, level = numeric

            current = _SectionDraft(
                markdown_depth=markdown_depth,
                heading_line=raw_line.rstrip(),
                heading_text=heading_text,
                path=path,
                title=title,
                level=level,
                file_order=file_order,
            )
            file_order += 1
            continue

        if current is None:
            preamble.append(raw_line)
        else:
            current.body_lines.append(raw_line)

    if current is not None:
        sections.append(current)

    return preamble, sections, irregularities


def _detect_body_content_patterns(sections: list[_SectionDraft]) -> list[Irregularity]:
    irregularities: list[Irregularity] = []
    table_row_re = re.compile(r"^\|.+\|$")
    ordered_list_re = re.compile(r"^\d+\.\s+")

    for section in sections:
        if not section.body:
            continue

        body_lines = section.body.splitlines()
        table_rows = [line for line in body_lines if table_row_re.match(line.strip())]
        if table_rows:
            irregularities.append(
                Irregularity(
                    kind="markdown_table_in_body",
                    description=(
                        f"Section {section.path or section.heading_text} contains a "
                        f"markdown table ({len(table_rows)} row(s))."
                    ),
                    handling=(
                        "Table lines are kept in section body; only markdown # lines are "
                        "treated as headings."
                    ),
                    location=section.heading_line,
                )
            )

        list_items = [line for line in body_lines if ordered_list_re.match(line.strip())]
        if list_items:
            irregularities.append(
                Irregularity(
                    kind="ordered_list_in_body",
                    description=(
                        f"Section {section.path or section.heading_text} contains an "
                        f"ordered list ({len(list_items)} item(s)) that could be mistaken "
                        "for numbered headings."
                    ),
                    handling=(
                        "List items stay in body because they lack a leading # marker."
                    ),
                    location=section.heading_line,
                )
            )

    return irregularities


def _detect_file_order_issues(sections: list[_SectionDraft]) -> list[Irregularity]:
    irregularities: list[Irregularity] = []
    last_path_by_parent: dict[str, str] = {}

    numbered = [section for section in sections if section.path is not None]
    for index, section in enumerate(numbered):
        assert section.path is not None
        parent_path = ".".join(section.path.split(".")[:-1]) or ROOT_LOGICAL_ID
        previous = last_path_by_parent.get(parent_path)
        if previous is not None and path_sort_key(section.path) < path_sort_key(previous):
            irregularities.append(
                Irregularity(
                    kind="file_order_mismatch",
                    description=(
                        f"Section {section.path} ({section.title}) appears in the file "
                        f"after {previous} but numeric order says it should come before."
                    ),
                    handling=(
                        "Sibling order is determined by numeric path sorting, not file order."
                    ),
                    location=section.heading_line,
                )
            )
        last_path_by_parent[parent_path] = section.path

    return irregularities


def _detect_markdown_depth_mismatches(sections: list[_SectionDraft]) -> list[Irregularity]:
    irregularities: list[Irregularity] = []
    for section in sections:
        if section.path is None:
            continue
        expected_depth = section.level + 1
        if section.markdown_depth != expected_depth:
            irregularities.append(
                Irregularity(
                    kind="markdown_depth_mismatch",
                    description=(
                        f"Heading {section.path} uses {section.markdown_depth} markdown "
                        f"# markers but numeric prefix implies level {section.level} "
                        f"(expected {expected_depth} # markers)."
                    ),
                    handling="Node level and parent assignment use numeric prefix depth only.",
                    location=section.heading_line,
                )
            )
    return irregularities


def _detect_duplicate_titles(sections: list[_SectionDraft]) -> list[Irregularity]:
    irregularities: list[Irregularity] = []
    title_to_paths: dict[str, list[str]] = {}

    for section in sections:
        if section.path is None:
            continue
        title_to_paths.setdefault(section.title, []).append(section.path)

    for title, paths in title_to_paths.items():
        if len(paths) > 1:
            irregularities.append(
                Irregularity(
                    kind="duplicate_heading_title",
                    description=(
                        f"Heading title {title!r} appears at multiple paths: "
                        f"{', '.join(paths)}."
                    ),
                    handling=(
                        "Each path produces a distinct node with its own logical_id, parent, "
                        "and body."
                    ),
                )
            )
    return irregularities


def parse_markdown(text: str) -> tuple[TreeNode, list[Irregularity]]:
    """Parse raw markdown into a tree rooted at a synthetic document node."""
    irregularities: list[Irregularity] = []
    preamble, sections, _ = _split_sections(text)

    if not sections:
        root = TreeNode(
            heading="[Document Root]",
            level=0,
            path=ROOT_LOGICAL_ID,
            logical_id=ROOT_LOGICAL_ID,
            body="\n".join(preamble).strip(),
            content_hash="",
            order_index=0,
        )
        return root, irregularities

    title_section = sections[0]
    if title_section.path is None:
        root_heading = title_section.heading_text
        root_body_parts = list(title_section.body_lines)
        content_sections = sections[1:]
        irregularities.append(
            Irregularity(
                kind="unnumbered_document_title",
                description=(
                    f"Document title {root_heading!r} has no numeric prefix."
                ),
                handling="Used as the synthetic root node heading; not a numbered section.",
                location=title_section.heading_line,
            )
        )
    else:
        root_heading = "[Document Root]"
        root_body_parts = []
        content_sections = sections

    if preamble or (title_section.path is None and title_section.body):
        orphan_body = "\n".join(preamble + root_body_parts).strip()
        if orphan_body:
            irregularities.append(
                Irregularity(
                    kind="orphan_preamble_content",
                    description=(
                        "Content appears before the first numbered heading "
                        f"({orphan_body[:80]!r}{'...' if len(orphan_body) > 80 else ''})."
                    ),
                    handling="Attached to the synthetic root node body and logged.",
                    location="before first numbered section",
                )
            )
            if "<!--" in orphan_body:
                irregularities.append(
                    Irregularity(
                        kind="html_comment_in_preamble",
                        description="HTML comment found in pre-heading content.",
                        handling="Preserved verbatim in root node body.",
                        location=orphan_body.splitlines()[0] if orphan_body else None,
                    )
                )
    else:
        orphan_body = "\n".join(preamble + root_body_parts).strip()

    root = TreeNode(
        heading=root_heading,
        level=0,
        path=ROOT_LOGICAL_ID,
        logical_id=ROOT_LOGICAL_ID,
        body=orphan_body,
        content_hash="",
        order_index=0,
    )

    numbered_sections = [section for section in content_sections if section.path is not None]
    unnumbered_sections = [section for section in content_sections if section.path is None]

    for section in unnumbered_sections:
        irregularities.append(
            Irregularity(
                kind="unnumbered_heading",
                description=f"Heading {section.heading_text!r} has no numeric prefix.",
                handling="Skipped as a structural section; body merged is not attempted.",
                location=section.heading_line,
            )
        )

    irregularities.extend(_detect_markdown_depth_mismatches(numbered_sections))
    irregularities.extend(_detect_file_order_issues(numbered_sections))
    irregularities.extend(_detect_duplicate_titles(numbered_sections))
    irregularities.extend(_detect_body_content_patterns(numbered_sections))

    nodes_by_path: dict[str, TreeNode] = {}
    known_paths: set[str] = set()

    for section in sorted(numbered_sections, key=lambda item: path_sort_key(item.path or "")):
        assert section.path is not None
        node = TreeNode(
            heading=section.heading_text,
            level=section.level,
            path=section.path,
            logical_id=section.path,
            body=section.body,
            content_hash="",
            order_index=0,
        )
        nodes_by_path[section.path] = node
        known_paths.add(section.path)

    for section in sorted(numbered_sections, key=lambda item: path_sort_key(item.path or "")):
        assert section.path is not None
        node = nodes_by_path[section.path]
        parent_path = find_parent_path(section.path, known_paths)

        if parent_path is None:
            node.parent = root
            root.children.append(node)
            continue

        expected_parent_path = ".".join(section.path.split(".")[:-1])
        if parent_path != expected_parent_path:
            irregularities.append(
                Irregularity(
                    kind="missing_intermediate_parent",
                    description=(
                        f"Section {section.path} implies parent {expected_parent_path}, "
                        f"but that heading does not exist."
                    ),
                    handling=f"Attached to nearest existing ancestor at path {parent_path}.",
                    location=section.heading_line,
                )
            )

        parent_node = nodes_by_path[parent_path]
        node.parent = parent_node
        parent_node.children.append(node)

    for parent in [root, *nodes_by_path.values()]:
        parent.children.sort(key=lambda child: path_sort_key(child.path))
        for sibling_order, child in enumerate(parent.children):
            child.order_index = sibling_order

    if irregularities:
        for item in irregularities:
            logger.info(
                "Parser irregularity [%s]: %s — %s",
                item.kind,
                item.description,
                item.handling,
            )

    return root, irregularities


def format_tree(
    node: TreeNode,
    *,
    show_body: bool = False,
    max_body_chars: int = 80,
    indent: int = 0,
) -> list[str]:
    lines: list[str] = []
    prefix = "  " * indent
    body_hint = ""
    if show_body and node.body:
        snippet = " ".join(node.body.split())
        if len(snippet) > max_body_chars:
            snippet = snippet[: max_body_chars - 3] + "..."
        body_hint = f" | body: {snippet!r}"

    lines.append(
        f"{prefix}- [{node.logical_id}] L{node.level} {node.heading!r}"
        f" (order={node.order_index}, hash={node.content_hash[:8]}...){body_hint}"
    )
    for child in node.children:
        lines.extend(
            format_tree(
                child,
                show_body=show_body,
                max_body_chars=max_body_chars,
                indent=indent + 1,
            )
        )
    return lines


def print_tree(
    root: TreeNode,
    *,
    show_body: bool = False,
    stream: Literal["stdout"] | None = None,
) -> None:
    import sys

    out = sys.stdout if stream is None else stream
    for line in format_tree(root, show_body=show_body):
        print(line, file=out)


def parse_markdown_file(path: str | Path) -> tuple[TreeNode, list[Irregularity]]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_markdown(text)


def _default_manual_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "ct200_manual.md"


if __name__ == "__main__":
    import argparse
    import logging

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
