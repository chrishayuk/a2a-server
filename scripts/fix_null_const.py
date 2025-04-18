#!/usr/bin/env python3
"""
fix_null_const.py - Fix JSON Schema null-const values for datamodel-code-generator

This script reads a JSON Schema file, finds any `const: null` or
`anyOf`/`oneOf` entries containing `const: null`, and replaces them
with the equivalent `type: "null"`. Outputs a new file with `_fixed`
appended before the `.json` extension.
"""

import json
import sys
import os
from typing import Any, Tuple, List

def fix_null_const(obj: Any, path: str = "") -> Tuple[Any, List[str]]:
    """
    Recursively traverse `obj` (dict or list), replace any `const: null`
    with `type: "null"`, and similarly in anyOf/oneOf arrays.

    Returns the modified object and a list of JSON paths where fixes occurred.
    """
    fixed_paths: List[str] = []

    if isinstance(obj, dict):
        # Direct const: null → type: null
        if obj.get("const", "__no_const__") is None:
            obj.pop("const", None)
            obj["type"] = "null"
            fixed_paths.append(path or "$")

        # anyOf/oneOf entries
        for key in ("anyOf", "oneOf"):
            if key in obj and isinstance(obj[key], list):
                for idx, entry in enumerate(obj[key]):
                    if isinstance(entry, dict) and entry.get("const") is None:
                        obj[key][idx] = {"type": "null"}
                        fixed_paths.append(f"{path or '$'}.{key}[{idx}]")

        # Recurse into all dict values
        for k, v in list(obj.items()):
            sub_path = f"{path}.{k}" if path else k
            new_v, sub_paths = fix_null_const(v, sub_path)
            obj[k] = new_v
            fixed_paths.extend(sub_paths)

    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            sub_path = f"{path}[{idx}]"
            new_item, sub_paths = fix_null_const(item, sub_path)
            obj[idx] = new_item
            fixed_paths.extend(sub_paths)

    return obj, fixed_paths

def main():
    if len(sys.argv) not in (2, 3):
        print(f"Usage: {sys.argv[0]} <input_schema.json> [output_schema.json]")
        sys.exit(1)

    input_path = sys.argv[1]
    # Derive output filename if not provided
    if len(sys.argv) == 3:
        output_path = sys.argv[2]
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_fixed{ext}"

    if not os.path.isfile(input_path):
        print(f"Error: input file '{input_path}' does not exist")
        sys.exit(1)

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as e:
        print(f"Error reading JSON schema: {e}")
        sys.exit(1)

    fixed_schema, fixed_paths = fix_null_const(schema)

    if fixed_paths:
        print(f"Fixed {len(fixed_paths)} null-const issues:")
        for p in fixed_paths:
            print("  -", p)
    else:
        print("No null-const issues found.")

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(fixed_schema, f, indent=2)
        print(f"Written fixed schema to: {output_path}")
    except Exception as e:
        print(f"Error writing fixed schema: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
