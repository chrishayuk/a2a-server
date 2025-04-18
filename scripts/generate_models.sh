#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# generate_models.sh – Generate Pydantic v2 compatible models
# with better handling of nullable unions
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

SCHEMA_PATH="${1:-$REPO_ROOT/spec/a2a_spec.json}"
OUTPUT_PATH="${2:-$REPO_ROOT/src/a2a/models.py}"

# Ensure directories exist
mkdir -p "$(dirname "$OUTPUT_PATH")"

# ---------------- 0. Ensure code‑gen is up‑to‑date -------------------------
echo "[generate_models] Ensuring datamodel-code-generator ≥ 0.25.8..."
pip install --upgrade "datamodel-code-generator>=0.25.8"

# --------------- 1. Fix schema for null‐const values ----------------------
echo "[generate_models] Patching schema for null constants..."
FIXED_SCHEMA="${SCHEMA_PATH%.*}_fixed.json"
python3 "$SCRIPT_DIR/fix_null_const.py" \
    "$SCHEMA_PATH" \
    "$FIXED_SCHEMA"

# ---------------- 2. Generate initial models ------------------------------
echo "[generate_models] Generating initial Pydantic v2 models..."
TEMP_OUTPUT="${OUTPUT_PATH}.temp"
python3 -m datamodel_code_generator \
  --input "$FIXED_SCHEMA" \
  --input-file-type jsonschema \
  --output "$TEMP_OUTPUT" \
  --output-model-type "pydantic_v2.BaseModel" \
  --base-class "pydantic.BaseModel" \
  --use-field-description \
  --use-schema-description \
  --use-annotated \
  --field-constraints \
  --use-union-operator \
  --target-python-version 3.11 \
  --snake-case-field \
  --allow-population-by-field-name \
  --disable-timestamp

# ---------------- 3. Post‑process unions & nullable fields ----------------
echo "[generate_models] Post‑processing models to fix unions & nullable fields..."
python3 "$SCRIPT_DIR/fix_pydantic_generator.py" \
    "$TEMP_OUTPUT" \
    "$OUTPUT_PATH"

# ---------------- 4. Clean up temporary files ----------------------------
echo "[generate_models] Cleaning up temporary files..."
rm -f "$FIXED_SCHEMA" "$TEMP_OUTPUT"

echo "[generate_models] ✅ Generated $OUTPUT_PATH"