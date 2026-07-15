from pathlib import Path

from app.parser import TreeNode, parse_markdown_file


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "ct200_manual.md"


def _nodes_by_logical_id(root: TreeNode) -> dict[str, TreeNode]:
    nodes = {root.logical_id: root}
    stack = list(root.children)

    while stack:
        node = stack.pop()
        nodes[node.logical_id] = node
        stack.extend(node.children)

    return nodes


def test_numeric_prefix_overrides_markdown_depth_and_file_order() -> None:
    root, _ = parse_markdown_file(FIXTURE_PATH)
    nodes = _nodes_by_logical_id(root)

    assert nodes["3.2"].parent is nodes["3"]
    assert nodes["3.2"].parent is not nodes["3.1"]
    assert nodes["3.3"].order_index < nodes["3.4"].order_index


def test_duplicate_heading_titles_get_distinct_nodes() -> None:
    root, _ = parse_markdown_file(FIXTURE_PATH)
    nodes = _nodes_by_logical_id(root)

    section_4_2 = nodes["4.2"]
    section_7_1 = nodes["7.1"]

    assert section_4_2.heading == "Error Codes"
    assert section_7_1.heading == "Error Codes"
    assert section_4_2 is not section_7_1
    assert section_4_2.parent is nodes["4"]
    assert section_7_1.parent is nodes["7"]
    assert section_4_2.parent is not section_7_1.parent
    assert section_4_2.content_hash != section_7_1.content_hash


def test_orphan_preamble_content_attached_to_root() -> None:
    root, _ = parse_markdown_file(FIXTURE_PATH)
    nodes = _nodes_by_logical_id(root)

    assert "<!-- TODO: confirm with regulatory -->" in root.body
    assert "<!-- TODO: confirm with regulatory -->" not in nodes["1"].body


def test_missing_intermediate_parent_falls_back_to_nearest_ancestor() -> None:
    root, _ = parse_markdown_file(FIXTURE_PATH)
    nodes = _nodes_by_logical_id(root)

    assert "2.1.1" not in nodes
    assert nodes["2.1.1.1"].parent is nodes["2.1"]
