from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVAL_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/eval_result.schema.json"
THROUGHPUT_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/live_throughput_result.schema.json"
MIC_LATENCY_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/mic_latency_result.schema.json"
LIVE_RUNTIME_SCHEMA_PATH = PROJECT_ROOT / "artifacts/schema/live_runtime_result.schema.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "artifacts/bench/capstone_evidence_manifest.json"
DEFAULT_EVAL_SUMMARY_PATH = PROJECT_ROOT / "artifacts/eval/summary-smoke.json"
DEFAULT_THROUGHPUT_PATH = PROJECT_ROOT / "artifacts/bench/live-throughput/live_throughput_result.json"
DEFAULT_MIC_LATENCY_PATH = PROJECT_ROOT / "artifacts/bench/mic-latency/mic_latency_result.json"
DEFAULT_LIVE_RUNTIME_GLOBS = [
    "artifacts/live/s02-smoke-*/live_runtime_result.json",
    "artifacts/live/s03-verify-*/live_runtime_result.json",
    "artifacts/live/s04-verify-*/live_runtime_result.json",
]
DEFAULT_COMPARE_SERVER_GLOBS = ["artifacts/live/s05-verify-server-*/server.log"]
DEFAULT_COMPARE_PYTEST_GLOBS = ["artifacts/live/s05-verify-pytest-*/pytest.log"]
PHASE_ORDER = ["evaluation", "throughput", "mic_latency", "live_runtime", "compare_ui"]


class EvidenceAssemblyError(RuntimeError):
    def __init__(self, phase: str, message: str, *, path: Path | None = None, stage: str | None = None) -> None:
        super().__init__(message)
        self.phase = phase
        self.path = path
        self.stage = stage or phase
        self.message = message


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path, *, kind: str) -> Any:
    if not path.exists():
        raise EvidenceAssemblyError(kind, f"{kind} artifact not found: {path}", path=path, stage=f"{kind}_missing")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvidenceAssemblyError(kind, f"{kind} artifact is not valid JSON: {exc}", path=path, stage=f"{kind}_malformed") from exc


def _load_text(path: Path, *, kind: str) -> str:
    if not path.exists():
        raise EvidenceAssemblyError(kind, f"{kind} proof output not found: {path}", path=path, stage=f"{kind}_missing")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceAssemblyError(kind, f"{kind} proof output could not be read: {path}: {exc}", path=path, stage=f"{kind}_unreadable") from exc


def _validate_payload(payload: Any, schema_path: Path, *, kind: str, artifact_path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EvidenceAssemblyError(kind, f"{kind} artifact root must be a JSON object: {artifact_path}", path=artifact_path, stage=f"{kind}_malformed")

    schema = _load_json(schema_path, kind=f"{kind} schema")
    if not isinstance(schema, dict):
        raise EvidenceAssemblyError(kind, f"{kind} schema root must be an object: {schema_path}", path=schema_path, stage=f"{kind}_schema_invalid")

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        pointer = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in first.path) if first.path else "/"
        raise EvidenceAssemblyError(
            kind,
            f"{kind} artifact failed schema validation at {pointer}: {first.message}",
            path=artifact_path,
            stage=f"{kind}_invalid",
        )
    return payload


def _tail_lines(text: str, limit: int = 12) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-limit:])


def _discover_latest(patterns: Iterable[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(sorted(PROJECT_ROOT.glob(pattern)))
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: (path.stat().st_mtime_ns, path.as_posix()))


def _resolve_path(explicit: Path | None, *, patterns: Iterable[str], kind: str) -> Path:
    if explicit is not None:
        return explicit
    discovered = _discover_latest(patterns)
    if discovered is None:
        raise EvidenceAssemblyError(kind, f"unable to discover a default {kind} artifact", stage=f"{kind}_missing")
    return discovered


def _summary_from_eval(payload: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    return {
        "artifact_path": str(artifact_path),
        "status": payload.get("status"),
        "pass": payload.get("pass"),
        "passes_threshold": payload.get("passes_threshold"),
        "track_count": payload.get("track_count"),
        "vocal_sdr_median_db": payload.get("vocal_sdr_median_db"),
        "threshold_db": payload.get("threshold_db"),
        "error_stage": payload.get("error_stage"),
        "generated_at": payload.get("generated_at"),
    }


def _summary_from_throughput(payload: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    return {
        "artifact_path": str(artifact_path),
        "status": payload.get("status"),
        "phase": payload.get("phase"),
        "error_stage": payload.get("error_stage"),
        "error_message": payload.get("error_message"),
        "wall_clock_ms": payload.get("wall_clock_ms"),
        "wall_clock_ms_per_chunk": payload.get("wall_clock_ms_per_chunk"),
        "throughput_chunks_per_second": payload.get("throughput_chunks_per_second"),
        "live_cli_exit_code": payload.get("live_cli_exit_code"),
        "live_runtime_status": payload.get("live_runtime_status"),
    }


def _summary_from_mic_latency(payload: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    return {
        "artifact_path": str(artifact_path),
        "status": payload.get("status"),
        "phase": payload.get("phase"),
        "error_stage": payload.get("error_stage"),
        "error_message": payload.get("error_message"),
        "capture_backend_name": payload.get("capture_backend_name"),
        "capture_duration_s": payload.get("capture_duration_s"),
        "capture_latency_ms": payload.get("capture_latency_ms"),
        "end_to_end_latency_ms": payload.get("end_to_end_latency_ms"),
        "live_cli_exit_code": payload.get("live_cli_exit_code"),
        "live_runtime_status": payload.get("live_runtime_status"),
    }


def _summary_from_live_runtime(payload: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    return {
        "artifact_path": str(artifact_path),
        "status": payload.get("status"),
        "error_stage": payload.get("error_stage"),
        "error_message": payload.get("error_message"),
        "health_state": payload.get("health_state"),
        "health_reason": payload.get("health_reason"),
        "queue_depth": payload.get("queue_depth"),
        "drop_count": payload.get("drop_count"),
    }


def _parse_compare_ui(server_log: Path, pytest_log: Path) -> dict[str, Any]:
    server_text = _load_text(server_log, kind="compare_ui_server")
    pytest_text = _load_text(pytest_log, kind="compare_ui_pytest")

    server_started = "compare-demo: serving" in server_text and "/ui/compare/" in server_text
    pytest_passed = False
    passed_match = re.search(r"(\d+) passed", pytest_text)
    failed_match = re.search(r"(\d+) failed", pytest_text)
    skipped_match = re.search(r"(\d+) skipped", pytest_text)
    if passed_match and int(passed_match.group(1)) > 0 and (not failed_match or int(failed_match.group(1)) == 0):
        pytest_passed = True

    status = "ok" if server_started and pytest_passed else "error"
    error_message = None
    if not server_started:
        error_message = f"compare UI server log did not show a successful launch: {server_log}"
    elif not pytest_passed:
        error_message = f"compare UI pytest log did not report a passing suite: {pytest_log}"

    return {
        "artifact_path": str(server_log.parent),
        "status": status,
        "phase": "complete" if status == "ok" else "compare_ui_failed",
        "error_stage": None if status == "ok" else "compare_ui_failed",
        "error_message": error_message,
        "server_log_path": str(server_log),
        "pytest_log_path": str(pytest_log),
        "server_started": server_started,
        "pytest_passed": pytest_passed,
        "passed": int(passed_match.group(1)) if passed_match else None,
        "failed": int(failed_match.group(1)) if failed_match else None,
        "skipped": int(skipped_match.group(1)) if skipped_match else None,
        "server_excerpt": _tail_lines(server_text),
        "pytest_excerpt": _tail_lines(pytest_text),
    }


def _phase_result(
    name: str,
    status: str,
    artifact_path: str | None,
    *,
    error_stage: str | None = None,
    error_message: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "artifact_path": artifact_path,
        "error_stage": error_stage,
        "error_message": error_message,
    }
    payload.update(details)
    return payload


def assemble_capstone_evidence(
    *,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    evaluation_summary_path: Path | None = None,
    throughput_artifact_path: Path | None = None,
    mic_latency_artifact_path: Path | None = None,
    live_runtime_artifact_path: Path | None = None,
    compare_server_log_path: Path | None = None,
    compare_pytest_log_path: Path | None = None,
) -> tuple[dict[str, Any], int]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_eval = _resolve_path(evaluation_summary_path or DEFAULT_EVAL_SUMMARY_PATH, patterns=[], kind="evaluation")
    resolved_throughput = _resolve_path(
        throughput_artifact_path or DEFAULT_THROUGHPUT_PATH,
        patterns=[],
        kind="throughput",
    )
    resolved_mic = _resolve_path(mic_latency_artifact_path or DEFAULT_MIC_LATENCY_PATH, patterns=[], kind="mic_latency")
    resolved_live = _resolve_path(
        live_runtime_artifact_path,
        patterns=DEFAULT_LIVE_RUNTIME_GLOBS,
        kind="live_runtime",
    )
    resolved_server_log = _resolve_path(
        compare_server_log_path,
        patterns=DEFAULT_COMPARE_SERVER_GLOBS,
        kind="compare_ui_server",
    )
    resolved_pytest_log = _resolve_path(
        compare_pytest_log_path,
        patterns=DEFAULT_COMPARE_PYTEST_GLOBS,
        kind="compare_ui_pytest",
    )

    phases: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}

    try:
        eval_payload = _validate_payload(_load_json(resolved_eval, kind="evaluation"), EVAL_SCHEMA_PATH, kind="evaluation", artifact_path=resolved_eval)
        phases.append(_phase_result("evaluation", str(eval_payload.get("status", "error")), str(resolved_eval), summary=_summary_from_eval(eval_payload, resolved_eval)))
        inputs["evaluation_summary_path"] = str(resolved_eval)

        throughput_payload = _validate_payload(
            _load_json(resolved_throughput, kind="throughput"),
            THROUGHPUT_SCHEMA_PATH,
            kind="throughput",
            artifact_path=resolved_throughput,
        )
        phases.append(
            _phase_result(
                "throughput",
                str(throughput_payload.get("status", "error")),
                str(resolved_throughput),
                error_stage=str(throughput_payload.get("error_stage")) if throughput_payload.get("error_stage") is not None else None,
                error_message=str(throughput_payload.get("error_message")) if throughput_payload.get("error_message") is not None else None,
                summary=_summary_from_throughput(throughput_payload, resolved_throughput),
            )
        )
        inputs["throughput_artifact_path"] = str(resolved_throughput)

        mic_payload = _validate_payload(
            _load_json(resolved_mic, kind="mic_latency"),
            MIC_LATENCY_SCHEMA_PATH,
            kind="mic_latency",
            artifact_path=resolved_mic,
        )
        phases.append(
            _phase_result(
                "mic_latency",
                str(mic_payload.get("status", "error")),
                str(resolved_mic),
                error_stage=str(mic_payload.get("error_stage")) if mic_payload.get("error_stage") is not None else None,
                error_message=str(mic_payload.get("error_message")) if mic_payload.get("error_message") is not None else None,
                summary=_summary_from_mic_latency(mic_payload, resolved_mic),
            )
        )
        inputs["mic_latency_artifact_path"] = str(resolved_mic)

        live_payload = _validate_payload(
            _load_json(resolved_live, kind="live_runtime"),
            LIVE_RUNTIME_SCHEMA_PATH,
            kind="live_runtime",
            artifact_path=resolved_live,
        )
        phases.append(
            _phase_result(
                "live_runtime",
                str(live_payload.get("status", "error")),
                str(resolved_live),
                summary=_summary_from_live_runtime(live_payload, resolved_live),
            )
        )
        inputs["live_runtime_artifact_path"] = str(resolved_live)

        compare_ui = _parse_compare_ui(resolved_server_log, resolved_pytest_log)
        phases.append(
            _phase_result(
                "compare_ui",
                compare_ui["status"],
                compare_ui["artifact_path"],
                error_stage=compare_ui["error_stage"],
                error_message=compare_ui["error_message"],
                server_log_path=compare_ui["server_log_path"],
                pytest_log_path=compare_ui["pytest_log_path"],
                server_started=compare_ui["server_started"],
                pytest_passed=compare_ui["pytest_passed"],
                passed=compare_ui["passed"],
                failed=compare_ui["failed"],
                skipped=compare_ui["skipped"],
                server_excerpt=compare_ui["server_excerpt"],
                pytest_excerpt=compare_ui["pytest_excerpt"],
            )
        )
        inputs["compare_server_log_path"] = str(resolved_server_log)
        inputs["compare_pytest_log_path"] = str(resolved_pytest_log)

        overall_status = "ok" if all(phase.get("status") == "ok" for phase in phases) else "error"
        failing_phase = next((phase for phase in phases if phase.get("status") != "ok"), None)
        result = {
            "status": overall_status,
            "phase": "complete" if overall_status == "ok" else str(failing_phase.get("name", "assembly_failed")),
            "error_stage": None if overall_status == "ok" else str(failing_phase.get("error_stage") or failing_phase.get("name") or "assembly_failed"),
            "error_message": None if overall_status == "ok" else str(failing_phase.get("error_message") or f"{failing_phase.get('name')} phase reported failure"),
            "generated_at": _now_iso(),
            "manifest_path": str(output_path),
            "phase_order": PHASE_ORDER,
            "phases": phases,
            "inputs": inputs,
        }
        _write_json(output_path, result)
        return result, 0 if overall_status == "ok" else 1

    except EvidenceAssemblyError as exc:
        phases.append(
            _phase_result(
                exc.phase,
                "error",
                str(exc.path) if exc.path is not None else None,
                error_stage=exc.stage,
                error_message=exc.message,
            )
        )
        result = {
            "status": "error",
            "phase": exc.phase,
            "error_stage": exc.stage,
            "error_message": exc.message,
            "generated_at": _now_iso(),
            "manifest_path": str(output_path),
            "phase_order": PHASE_ORDER,
            "phases": phases,
            "inputs": inputs,
        }
        _write_json(output_path, result)
        return result, 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble the final capstone evidence bundle manifest.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Path for the assembled manifest JSON.")
    parser.add_argument("--evaluation-summary", type=Path, default=None, help="Path to the final evaluation summary JSON.")
    parser.add_argument("--throughput-artifact", type=Path, default=None, help="Path to the live throughput result JSON.")
    parser.add_argument("--mic-latency-artifact", type=Path, default=None, help="Path to the mic latency result JSON.")
    parser.add_argument("--live-runtime-artifact", type=Path, default=None, help="Path to the live runtime result JSON.")
    parser.add_argument("--compare-server-log", type=Path, default=None, help="Path to the compare UI server log.")
    parser.add_argument("--compare-pytest-log", type=Path, default=None, help="Path to the compare UI pytest log.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        _, exit_code = assemble_capstone_evidence(
            output_path=args.output,
            evaluation_summary_path=args.evaluation_summary,
            throughput_artifact_path=args.throughput_artifact,
            mic_latency_artifact_path=args.mic_latency_artifact,
            live_runtime_artifact_path=args.live_runtime_artifact,
            compare_server_log_path=args.compare_server_log,
            compare_pytest_log_path=args.compare_pytest_log,
        )
    except Exception as exc:  # pragma: no cover - defensive guard for unexpected failures
        failure_payload = {
            "status": "error",
            "phase": "assembly_failed",
            "error_stage": "assembly_failed",
            "error_message": str(exc),
            "generated_at": _now_iso(),
            "manifest_path": str(Path(args.output)),
            "phase_order": PHASE_ORDER,
            "phases": [],
            "inputs": {},
        }
        _write_json(Path(args.output), failure_payload)
        print(f"capstone_evidence_assembly_failed: {exc}", file=sys.stderr)
        return 1

    if exit_code == 0:
        print(f"capstone_evidence_manifest: {args.output}")
    else:
        print(f"capstone_evidence_assembly_failed[{argv or sys.argv[1:]}]: {args.output}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
