from pathlib import Path
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models import Node
from app.parser import parse_markdown_file


def get_nodes_map(root):
    nodes = {root.logical_id: root}
    stack = list(root.children)
    while stack:
        node = stack.pop()
        nodes[node.logical_id] = node
        stack.extend(node.children)
    return nodes


def test_v2_ingest_flags_changed_nodes(
    client: TestClient, v1_path: Path, v2_path: Path
) -> None:
    # 1. Ingest ct200_manual.md (v1)
    res1 = client.post(
        "/documents/ingest",
        json={"name": "CT200 Manual", "file_path": str(v1_path)},
    )
    assert res1.status_code == 201
    doc_id = res1.json()["document"]["id"]

    # 2. Ingest ct200_manual_v2.md (v2) under same document
    res2 = client.post(f"/documents/{doc_id}/ingest", json={"file_path": str(v2_path)})
    assert res2.status_code == 201

    changes = res2.json()["changes"]
    assert changes is not None

    changed_ids = {item["logical_id"] for item in changes["changed"]}
    inserted_ids = {item["logical_id"] for item in changes["inserted"]}
    removed_ids = {item["logical_id"] for item in changes["removed"]}

    # Assert logical_ids '3.2','4.2','2.1.1.1','4.3' flagged changed
    for lid in ["3.2", "4.2", "2.1.1.1", "4.3"]:
        assert lid in changed_ids, f"Expected {lid} to be in changed list"

    # '1.1' unchanged (should not be in changed, inserted, or removed)
    assert "1.1" not in changed_ids
    assert "1.1" not in inserted_ids
    assert "1.1" not in removed_ids


def test_v1_nodes_survive_v2_ingest(
    client: TestClient, db_session: Session, v1_path: Path, v2_path: Path
) -> None:
    # Ingest v1
    res1 = client.post(
        "/documents/ingest",
        json={"name": "CT200 Manual", "file_path": str(v1_path)},
    )
    assert res1.status_code == 201
    doc_id = res1.json()["document"]["id"]
    v1_version_id = res1.json()["version"]["id"]

    # Ingest v2
    res2 = client.post(f"/documents/{doc_id}/ingest", json={"file_path": str(v2_path)})
    assert res2.status_code == 201

    # Query v1 nodes directly
    v1_nodes = db_session.query(Node).filter(Node.version_id == v1_version_id).all()
    assert len(v1_nodes) == 28, f"Expected 28 nodes, got {len(v1_nodes)}"

    # Parse v1 directly to get original hashes
    root_parsed, _ = parse_markdown_file(v1_path)
    parsed_map = get_nodes_map(root_parsed)

    db_map = {node.logical_id: node for node in v1_nodes}

    # Assert content_hash values match original v1 parse
    for logical_id, parsed_node in parsed_map.items():
        assert logical_id in db_map, f"Parsed node {logical_id} not found in DB v1 nodes"
        assert db_map[logical_id].content_hash == parsed_node.content_hash, (
            f"Hash mismatch for {logical_id}: "
            f"DB {db_map[logical_id].content_hash} vs Parsed {parsed_node.content_hash}"
        )


def test_new_section_flagged_as_inserted_not_changed(
    client: TestClient, v1_path: Path, v2_path: Path
) -> None:
    # Ingest v1
    res1 = client.post(
        "/documents/ingest",
        json={"name": "CT200 Manual", "file_path": str(v1_path)},
    )
    assert res1.status_code == 201
    doc_id = res1.json()["document"]["id"]

    # Ingest v2
    res2 = client.post(f"/documents/{doc_id}/ingest", json={"file_path": str(v2_path)})
    assert res2.status_code == 201

    changes = res2.json()["changes"]
    assert changes is not None

    changed_ids = {item["logical_id"] for item in changes["changed"]}
    inserted_ids = {item["logical_id"] for item in changes["inserted"]}

    # Assert '5.3' status == 'inserted' after v2 ingest, not matched against unrelated node
    assert "5.3" in inserted_ids, "Expected '5.3' to be in inserted list"
    assert "5.3" not in changed_ids, "Expected '5.3' to NOT be in changed list"
