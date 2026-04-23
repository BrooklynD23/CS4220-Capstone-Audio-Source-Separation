from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema


def _load_json(path: Path, kind: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"{kind} file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{kind} is not valid JSON: {exc}") from exc


def _json_pointer(path_parts: list[Any]) -> str:
    if not path_parts:
        return "/"
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in path_parts]
    return "/" + "/".join(encoded)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a JSON payload against a JSON schema.")
    parser.add_argument("--schema", required=True, help="Path to JSON schema")
    parser.add_argument("--input", required=True, help="Path to JSON payload")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        schema = _load_json(Path(args.schema), kind="schema")
        payload = _load_json(Path(args.input), kind="input")

        if not isinstance(schema, dict):
            raise ValueError("schema root must be an object")
        if not isinstance(payload, (dict, list)):
            raise ValueError("input top-level JSON type must be object or array")

        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            print(f"validation_failed: {len(errors)} error(s)", file=sys.stderr)
            for err in errors:
                pointer = _json_pointer(list(err.path))
                print(f"- path={pointer} message={err.message}", file=sys.stderr)
            return 1

        print("validation_ok")
        return 0

    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, jsonschema.SchemaError) as exc:
        print(f"validation_input_error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # pragma: no cover
        print(f"validation_error: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
