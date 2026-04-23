from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - only hits on broken envs
    pytest.fail(
        "Missing dependency 'pyyaml'. Install project deps first (e.g. `pip install -e .[dev]`).",
        pytrace=False,
    )

try:
    from jsonschema import Draft202012Validator
except ModuleNotFoundError:  # pragma: no cover - only hits on broken envs
    pytest.fail(
        "Missing dependency 'jsonschema'. Install project deps first (e.g. `pip install -e .[dev]`).",
        pytrace=False,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = PROJECT_ROOT / "scripts/eval/eval_protocol.yaml"
EVAL_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/eval_result.schema.json"
TIMING_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/timing_result.schema.json"

REQUIRED_PROTOCOL_KEYS = {
    "protocol_version",
    "dataset",
    "sample_rate_hz",
    "chunk_duration_s",
    "stems",
    "aggregation",
    "immutable_defaults",
}

REQUIRED_DATASET_KEYS = {"name", "split", "track_selection", "channels"}
REQUIRED_AGGREGATION_KEYS = {"metric", "threshold_db", "pass_condition"}
IMMUTABLE_DEFAULTS = {
    "dataset.split",
    "sample_rate_hz",
    "stems",
    "aggregation.metric",
    "aggregation.pass_condition",
}

MIN_SAMPLE_RATE_HZ = 8000
MAX_SAMPLE_RATE_HZ = 48000
MIN_CHUNK_DURATION_S = 0.1
MAX_CHUNK_DURATION_S = 30.0


class ProtocolValidationError(ValueError):
    """Validation error with optional structured context for tests and tooling."""

    def __init__(self, message: str, missing_keys: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing_keys = missing_keys or []


class ProtocolOverrideError(ValueError):
    """Raised when an override attempts to mutate immutable protocol defaults."""


def _set_nested(mapping: dict[str, Any], dotted_key: str, value: Any) -> None:
    cursor: dict[str, Any] = mapping
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def _flatten(prefix: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value}

    flattened: dict[str, Any] = {}
    for key, nested_value in value.items():
        full_key = f"{prefix}.{key}" if prefix else key
        flattened.update(_flatten(full_key, nested_value))
    return flattened


def load_protocol(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProtocolValidationError(f"Protocol file not found: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProtocolValidationError(f"Unable to read protocol file: {path}: {exc}") from exc

    if not raw.strip():
        raise ProtocolValidationError("Protocol YAML is empty", missing_keys=sorted(REQUIRED_PROTOCOL_KEYS))

    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        location = ""
        if getattr(exc, "problem_mark", None):
            mark = exc.problem_mark
            location = f" at line {mark.line + 1}, column {mark.column + 1}"
        detail = f"{type(exc).__name__}{location}: {exc}"
        raise ProtocolValidationError(f"Malformed protocol YAML{location}. {detail}") from exc

    if not isinstance(payload, dict):
        raise ProtocolValidationError("Protocol YAML must define a mapping at the root")

    validate_protocol(payload)
    return payload


def validate_protocol(protocol: dict[str, Any]) -> None:
    missing_root = sorted(REQUIRED_PROTOCOL_KEYS - protocol.keys())
    if missing_root:
        raise ProtocolValidationError("Protocol missing required root keys", missing_keys=missing_root)

    dataset = protocol["dataset"]
    if not isinstance(dataset, dict):
        raise ProtocolValidationError("dataset must be an object")

    missing_dataset = sorted(REQUIRED_DATASET_KEYS - dataset.keys())
    if missing_dataset:
        missing = [f"dataset.{key}" for key in missing_dataset]
        raise ProtocolValidationError("Protocol missing required dataset keys", missing_keys=missing)

    aggregation = protocol["aggregation"]
    if not isinstance(aggregation, dict):
        raise ProtocolValidationError("aggregation must be an object")

    missing_agg = sorted(REQUIRED_AGGREGATION_KEYS - aggregation.keys())
    if missing_agg:
        missing = [f"aggregation.{key}" for key in missing_agg]
        raise ProtocolValidationError("Protocol missing required aggregation keys", missing_keys=missing)

    sample_rate_hz = protocol["sample_rate_hz"]
    if not isinstance(sample_rate_hz, int):
        raise ProtocolValidationError("sample_rate_hz must be an integer")
    if not MIN_SAMPLE_RATE_HZ <= sample_rate_hz <= MAX_SAMPLE_RATE_HZ:
        raise ProtocolValidationError(
            f"sample_rate_hz must be between {MIN_SAMPLE_RATE_HZ} and {MAX_SAMPLE_RATE_HZ}"
        )

    chunk_duration = protocol["chunk_duration_s"]
    if not isinstance(chunk_duration, (int, float)):
        raise ProtocolValidationError("chunk_duration_s must be numeric")
    if not MIN_CHUNK_DURATION_S <= float(chunk_duration) <= MAX_CHUNK_DURATION_S:
        raise ProtocolValidationError(
            f"chunk_duration_s must be between {MIN_CHUNK_DURATION_S} and {MAX_CHUNK_DURATION_S}"
        )

    if not isinstance(protocol["stems"], list) or not protocol["stems"]:
        raise ProtocolValidationError("stems must be a non-empty list")

    threshold = aggregation["threshold_db"]
    if not isinstance(threshold, (int, float)):
        raise ProtocolValidationError("aggregation.threshold_db must be numeric")

    immutable_defaults = protocol["immutable_defaults"]
    if not isinstance(immutable_defaults, list):
        raise ProtocolValidationError("immutable_defaults must be a list of dotted-key paths")


def apply_overrides(protocol: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    candidate = deepcopy(protocol)
    immutable = set(protocol.get("immutable_defaults", []))
    for key, value in _flatten("", overrides).items():
        if key in immutable:
            raise ProtocolOverrideError(f"Override rejected for immutable field: {key}")
        _set_nested(candidate, key, value)

    validate_protocol(candidate)
    return candidate


def _load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def test_protocol_file_exists() -> None:
    assert PROTOCOL_PATH.exists(), f"Missing protocol file: {PROTOCOL_PATH}"


def test_protocol_contains_required_keys_and_defaults() -> None:
    protocol = load_protocol(PROTOCOL_PATH)

    assert protocol["dataset"]["split"] == "test"
    assert protocol["sample_rate_hz"] == 44100
    assert protocol["stems"] == ["vocals", "instrumental"]
    assert protocol["aggregation"]["metric"] == "vocal_sdr_median_db"
    assert protocol["aggregation"]["pass_condition"] == ">="

    assert set(protocol["immutable_defaults"]) == IMMUTABLE_DEFAULTS


def test_rejects_override_of_immutable_defaults() -> None:
    protocol = load_protocol(PROTOCOL_PATH)

    with pytest.raises(ProtocolOverrideError, match="immutable field: sample_rate_hz"):
        apply_overrides(protocol, {"sample_rate_hz": 48000})


def test_allows_mutable_override_within_bounds() -> None:
    protocol = load_protocol(PROTOCOL_PATH)

    updated = apply_overrides(protocol, {"chunk_duration_s": 5.0})
    assert updated["chunk_duration_s"] == 5.0


def test_empty_yaml_rejected() -> None:
    with pytest.raises(ProtocolValidationError, match="empty") as exc_info:
        load_protocol(_temp_yaml("", "empty_protocol.yaml"))

    assert set(exc_info.value.missing_keys) == REQUIRED_PROTOCOL_KEYS


def test_missing_required_keys_reported() -> None:
    payload = {
        "protocol_version": "1.0",
        "dataset": {"name": "musdb18"},
    }
    with pytest.raises(ProtocolValidationError, match="required") as exc_info:
        validate_protocol(payload)

    assert "sample_rate_hz" in exc_info.value.missing_keys
    assert "aggregation" in exc_info.value.missing_keys


def test_non_numeric_threshold_rejected() -> None:
    protocol = load_protocol(PROTOCOL_PATH)
    protocol["aggregation"]["threshold_db"] = "5.0"

    with pytest.raises(ProtocolValidationError, match="threshold_db must be numeric"):
        validate_protocol(protocol)


def test_unreadable_protocol_file_surfaces_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = "Permission denied"

    def _raise(*_: Any, **__: Any) -> str:
        raise OSError(marker)

    monkeypatch.setattr(Path, "read_text", _raise)

    with pytest.raises(ProtocolValidationError, match="Unable to read protocol file") as exc_info:
        load_protocol(PROTOCOL_PATH)

    assert marker in str(exc_info.value)


def test_malformed_yaml_reports_location() -> None:
    malformed = "protocol_version: 1\ndataset: [\n"

    with pytest.raises(ProtocolValidationError, match=r"line \d+, column \d+"):
        load_protocol(_temp_yaml(malformed, "malformed_protocol.yaml"))


@pytest.mark.parametrize(
    ("sample_rate", "chunk_duration"),
    [
        (MIN_SAMPLE_RATE_HZ, MIN_CHUNK_DURATION_S),
        (MAX_SAMPLE_RATE_HZ, MAX_CHUNK_DURATION_S),
    ],
)
def test_boundary_values_allowed(sample_rate: int, chunk_duration: float) -> None:
    protocol = load_protocol(PROTOCOL_PATH)
    protocol["sample_rate_hz"] = sample_rate
    protocol["chunk_duration_s"] = chunk_duration
    validate_protocol(protocol)


def validate_schema_version(schema: dict[str, Any]) -> None:
    expected = "https://json-schema.org/draft/2020-12/schema"
    actual = schema.get("$schema")
    if actual != expected:
        raise ProtocolValidationError(
            f"Invalid schema version: expected '{expected}', got '{actual}'"
        )


def test_invalid_schema_draft_rejected() -> None:
    invalid_schema = {
        "$schema": "https://json-schema.org/draft/1900-01/schema",
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
    }

    with pytest.raises(ProtocolValidationError, match="Invalid schema version"):
        validate_schema_version(invalid_schema)


def test_eval_and_timing_schemas_are_valid_draft_2020_12() -> None:
    for schema_path in (EVAL_SCHEMA_PATH, TIMING_SCHEMA_PATH):
        assert schema_path.exists(), f"Missing schema file: {schema_path}"
        schema = _load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_eval_schema_requires_verdict_fields() -> None:
    schema = _load_json(EVAL_SCHEMA_PATH)
    required = set(schema["required"])

    assert "vocal_sdr_median_db" in required
    assert "threshold_db" in required
    assert "pass" in required


def test_timing_schema_requires_stage_timings() -> None:
    schema = _load_json(TIMING_SCHEMA_PATH)
    required = set(schema["required"])

    assert "stft_ms" in required
    assert "infer_ms" in required
    assert "istft_ms" in required
    assert "total_ms" in required


def _temp_yaml(content: str, filename: str) -> Path:
    temp_dir = PROJECT_ROOT / ".pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = temp_dir / filename
    path.write_text(content, encoding="utf-8")
    return path
