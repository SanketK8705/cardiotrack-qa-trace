#!/usr/bin/env bash
# Demo assumes a clean or reset data/app.db and data/generations.json, matching
# the README "clean local run" instructions. It can run on a dirty DB because it
# captures IDs from each response, but the printed IDs will be easiest to follow
# after removing those files and restarting the server.

set -euo pipefail

SERVER_URL="${SERVER_URL:-http://127.0.0.1:8000}"
DB_PATH="${DB_PATH:-data/app.db}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $1" >&2
    exit 1
  fi
}

json_value() {
  local file="$1"
  local expr="$2"
  "$PYTHON_BIN" - "$file" "$expr" <<'PY'
import json
import sys

path, expr = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
for part in expr.split("."):
    if part.isdigit():
        data = data[int(part)]
    else:
        data = data[part]
print(data)
PY
}

assert_json_value() {
  local file="$1"
  local expr="$2"
  local expected="$3"
  local actual
  actual="$(json_value "$file" "$expr")"
  if [ "$actual" != "$expected" ]; then
    echo "ERROR: expected $expr to be $expected, got $actual" >&2
    exit 1
  fi
}

assert_generation_contains_changed_nodes() {
  local file="$1"
  "$PYTHON_BIN" - "$file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)

if data["staleness"]["is_stale"] is not True:
    raise SystemExit("ERROR: expected generation staleness.is_stale=true")

statuses = {
    node["logical_id"]: node["status"]
    for node in data["staleness"]["nodes"]
}
for logical_id in ("4.2", "3.2"):
    if statuses.get(logical_id) != "changed":
        raise SystemExit(
            f"ERROR: expected {logical_id} staleness status changed, got {statuses.get(logical_id)}"
        )
PY
}

request() {
  local method="$1"
  local path="$2"
  local expected_status="$3"
  local out_file="$4"
  local data="${5:-}"
  local status

  echo
  echo "### $method $path"

  if [ -n "$data" ]; then
    status="$(
      curl -sS -X "$method" "$SERVER_URL$path" \
        -H 'Content-Type: application/json' \
        -d "$data" \
        -o "$out_file" \
        -w '%{http_code}'
    )"
  else
    status="$(
      curl -sS -X "$method" "$SERVER_URL$path" \
        -o "$out_file" \
        -w '%{http_code}'
    )"
  fi

  echo "HTTP $status"
  if ! "$PYTHON_BIN" -m json.tool "$out_file"; then
    echo "(response was not JSON; raw body follows)"
    cat "$out_file"
    echo
  fi

  if [ "$status" != "$expected_status" ]; then
    echo "ERROR: expected HTTP $expected_status for $method $path, got $status" >&2
    exit 1
  fi
}

lookup_v1_node_id() {
  local document_id="$1"
  local logical_id="$2"
  local node_id

  node_id="$(
    sqlite3 "$DB_PATH" \
      "SELECT n.id
       FROM nodes n
       JOIN document_versions v ON v.id = n.version_id
       WHERE v.document_id = $document_id
         AND v.version_number = 1
         AND n.logical_id = '$logical_id'
       LIMIT 1;"
  )"

  if [ -z "$node_id" ]; then
    echo "ERROR: could not find v1 node ID for logical_id $logical_id in document $document_id" >&2
    exit 1
  fi

  echo "$node_id"
}

require_command curl
require_command sqlite3
require_command "$PYTHON_BIN"

health_file="$TMP_DIR/health.json"
request GET /health 200 "$health_file"

v1_file="$TMP_DIR/ingest_v1.json"
request POST /documents/ingest 201 "$v1_file" '{"name":"CT-200 Manual","file_path":"data/ct200_manual.md"}'
document_id="$(json_value "$v1_file" document.id)"
assert_json_value "$v1_file" version.version_number 1

node_42_id="$(lookup_v1_node_id "$document_id" "4.2")"
node_32_id="$(lookup_v1_node_id "$document_id" "3.2")"

echo
echo "### v1 node IDs selected from SQLite"
echo "document_id=$document_id"
echo "4.2 node_id=$node_42_id"
echo "3.2 node_id=$node_32_id"

selection_file="$TMP_DIR/selection.json"
request POST /selections 201 "$selection_file" "{\"name\":\"v1 alarm and inflation checks\",\"node_ids\":[$node_42_id,$node_32_id]}"
selection_id="$(json_value "$selection_file" id)"

generation_one_file="$TMP_DIR/generation_one.json"
request POST "/selections/$selection_id/generate" 200 "$generation_one_file"
assert_json_value "$generation_one_file" status success
generation_one_id="$(json_value "$generation_one_file" generation_id)"

v2_file="$TMP_DIR/ingest_v2.json"
request POST "/documents/$document_id/ingest" 201 "$v2_file" '{"file_path":"data/ct200_manual_v2.md"}'
assert_json_value "$v2_file" version.version_number 2

diff_42_file="$TMP_DIR/diff_42.json"
request GET "/documents/$document_id/nodes/4.2/diff?from=1&to=2" 200 "$diff_42_file"
assert_json_value "$diff_42_file" changed True

diff_32_file="$TMP_DIR/diff_32.json"
request GET "/documents/$document_id/nodes/3.2/diff?from=1&to=2" 200 "$diff_32_file"
assert_json_value "$diff_32_file" changed True

generation_detail_file="$TMP_DIR/generation_detail.json"
request GET "/generations/$generation_one_id" 200 "$generation_detail_file"
assert_generation_contains_changed_nodes "$generation_detail_file"

generation_two_file="$TMP_DIR/generation_two.json"
request POST "/selections/$selection_id/generate" 200 "$generation_two_file"
assert_json_value "$generation_two_file" status success
generation_two_id="$(json_value "$generation_two_file" generation_id)"

if [ "$generation_one_id" = "$generation_two_id" ]; then
  echo "ERROR: duplicate submission reused generation_id $generation_one_id" >&2
  exit 1
fi

echo
echo "### duplicate generation policy"
echo "first_generation_id=$generation_one_id"
echo "second_generation_id=$generation_two_id"
echo "Result: second /generate call created a new generation record."

generations_list_file="$TMP_DIR/generations_for_selection.json"
request GET "/generations?selection_id=$selection_id" 200 "$generations_list_file"
