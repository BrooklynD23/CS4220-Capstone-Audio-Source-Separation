from __future__ import annotations

import json
import os
import math
import struct
import threading
import wave
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAYWRIGHT_LIBRARY_DIR = PROJECT_ROOT / ".cache/apt/extracted/usr/lib/x86_64-linux-gnu"
if PLAYWRIGHT_LIBRARY_DIR.exists():
    current_ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = f"{PLAYWRIGHT_LIBRARY_DIR}:{current_ld_library_path}".rstrip(":")

os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "1")

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

HEALTHY_FIXTURE = PROJECT_ROOT / "tests/fixtures/ui/compare/healthy.json"
MALFORMED_FIXTURE = PROJECT_ROOT / "tests/fixtures/ui/compare/malformed.json"
DEGRADED_FIXTURE = PROJECT_ROOT / "tests/fixtures/ui/compare/degraded.json"
FALLBACK_FIXTURE = PROJECT_ROOT / "tests/fixtures/ui/compare/fallback.json"
VIDEO_AUDIO_FIXTURE = PROJECT_ROOT / "tests/fixtures/ui/compare/video_audio.json"
COMPARE_BASE_URL = os.environ.get("COMPARE_DEMO_BASE_URL") or os.environ.get("BASE_URL")


class QuietHTTPRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003 - stdlib API
        pass


@pytest.fixture(scope="module")
def compare_server() -> str:
    if COMPARE_BASE_URL:
        yield COMPARE_BASE_URL.rstrip("/")
        return

    handler = partial(QuietHTTPRequestHandler, directory=str(PROJECT_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _load_compare_page(base_url: str):
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1400})
    page.goto(f"{base_url.rstrip('/')}/ui/compare/", wait_until="networkidle")
    return playwright, browser, page


def _load_fixture(page, fixture: Path) -> None:
    page.set_input_files("#artifact-file", str(fixture))
    page.click("#load-button")
    expected_label = f"Loaded file: {fixture.name}"
    page.wait_for_function(
        "label => document.querySelector('[data-testid=\"selected-file\"]').textContent === label",
        arg=expected_label,
    )


def _write_temp_fixture(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_temp_text_fixture(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _write_project_fixture(relative_path: str, payload: dict) -> Path:
    path = PROJECT_ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_wav_fixture(path: Path, *, frequency_hz: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 8000
    frames = bytearray()
    for index in range(sample_rate // 10):
        value = int(math.sin(2 * math.pi * frequency_hz * index / sample_rate) * 16000)
        frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))


def test_compare_ui_switches_modes_without_replacing_loaded_artifact(compare_server: str) -> None:
    playwright, browser, page = _load_compare_page(compare_server)
    try:
        _load_fixture(page, HEALTHY_FIXTURE)
        page.evaluate("window.__compareArtifactRef = window.__compareState.artifact")

        assert page.locator('[data-testid="compare-mode"]').text_content() == 'side-by-side'
        assert page.locator('[data-testid="compare-mode-title"]').text_content() == 'Side-by-side'
        assert page.locator('[data-testid="compare-canvas"]').get_attribute('data-mode') == 'side-by-side'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3
        assert page.locator('[data-testid="source-label"]').text_content() == 'native audio source'
        assert page.locator('[data-testid="compare-health"]').text_content() == 'healthy'
        assert page.locator('[data-testid="runtime-health-text"]').text_content() == 'healthy — runtime operating normally'
        assert page.locator('[data-testid="final-stems-label"]').text_content() == 'Final stems'
        assert page.locator('[data-testid="final-stems-details"]').text_content() == 'Vocals: artifacts/live/smoke/vocals.wav • Drums: artifacts/live/smoke/drums.wav • Bass: artifacts/live/smoke/bass.wav • Other: artifacts/live/smoke/other.wav • Queue depth: 0 • Drop count: 0'
        assert page.locator('[data-testid="stem-vocals"]').text_content() == 'artifacts/live/smoke/vocals.wav'
        assert page.locator('[data-testid="stem-drums"]').text_content() == 'artifacts/live/smoke/drums.wav'
        assert page.locator('[data-testid="stem-bass"]').text_content() == 'artifacts/live/smoke/bass.wav'
        assert page.locator('[data-testid="stem-other"]').text_content() == 'artifacts/live/smoke/other.wav'

        page.click('[data-testid="mode-button-overlay"]')
        page.wait_for_function("document.querySelector('[data-testid=\"compare-mode\"]').textContent === 'overlay'")
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="compare-canvas"]').get_attribute('data-mode') == 'overlay'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3

        page.click('[data-testid="mode-button-timeline"]')
        page.wait_for_function("document.querySelector('[data-testid=\"compare-mode\"]').textContent === 'timeline'")
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="compare-canvas"]').get_attribute('data-mode') == 'timeline'
        assert page.locator('[data-testid="stage-board"]').get_attribute('data-testid') == 'stage-board'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3
        stage_list_text = ' '.join(page.locator('[data-testid="stages-list"] li').all_text_contents())
        assert 'stft' in stage_list_text
        assert 'infer' in stage_list_text
        assert 'istft' in stage_list_text

        _load_fixture(page, DEGRADED_FIXTURE)
        assert page.locator('[data-testid="health-state"]').text_content() == 'degraded'
        assert page.locator('[data-testid="compare-health"]').text_content() == 'degraded'
        assert page.locator('[data-testid="queue-depth"]').text_content() == '4'
        assert page.locator('[data-testid="drop-count"]').text_content() == '1'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 4
        assert page.locator('[data-testid="runtime-health-text"]').text_content() == 'degraded — gpu queue saturated and dropped one late chunk'
        assert page.locator('[data-testid="final-stems-details"]').text_content() == 'Vocals: artifacts/live/degraded/vocals.wav • Drums: artifacts/live/degraded/drums.wav • Bass: artifacts/live/degraded/bass.wav • Other: artifacts/live/degraded/other.wav • Queue depth: 4 • Drop count: 1'

        _load_fixture(page, FALLBACK_FIXTURE)
        assert page.locator('[data-testid="health-state"]').text_content() == 'fallback'
        assert page.locator('[data-testid="fallback-applied"]').text_content() == 'Yes'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 1
        assert page.locator('[data-testid="final-stems-label"]').text_content() == 'Final stems'
        assert page.locator('[data-testid="final-stems-details"]').text_content() == 'Vocals: artifacts/live/fallback/vocals.wav • Drums: artifacts/live/fallback/drums.wav • Bass: artifacts/live/fallback/bass.wav • Other: artifacts/live/fallback/other.wav • Queue depth: 0 • Drop count: 0'
        assert page.locator('[data-testid="runtime-health-text"]').text_content() == 'fallback — fallback stem path used after worker timeout'

        _load_fixture(page, VIDEO_AUDIO_FIXTURE)
        assert page.locator('[data-testid="source-kind"]').text_content() == 'video-audio'
        assert page.locator('[data-testid="source-label"]').text_content() == 'audio-first extraction from video source'
        assert page.locator('[data-testid="runtime-source-text"]').text_content() == 'audio-first extraction from video source'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 5
        assert page.locator('[data-testid="final-stems-label"]').text_content() == 'Audio-first extraction'
        assert page.locator('[data-testid="final-stems-details"]').text_content() == 'Vocals: artifacts/live/video-audio/vocals.wav • Drums: artifacts/live/video-audio/drums.wav • Bass: artifacts/live/video-audio/bass.wav • Other: artifacts/live/video-audio/other.wav • Queue depth: 0 • Drop count: 0'
        assert page.locator('[data-testid="stage-board"]').get_attribute('data-testid') == 'stage-board'
    finally:
        browser.close()
        playwright.stop()


def test_compare_ui_requires_a_selected_file_before_loading(compare_server: str) -> None:
    playwright, browser, page = _load_compare_page(compare_server)
    try:
        page.click('#load-button')
        page.wait_for_function("document.querySelector('[data-testid=\"error-banner\"]').offsetParent !== null")

        error_text = page.locator('[data-testid="error-banner"]').text_content() or ''
        assert 'Select a JSON artifact before loading.' in error_text
        assert page.locator('[data-testid="status-banner"]').text_content() == 'Artifact load failed. Review the error banner and retry.'
        assert page.locator('[data-testid="selected-file"]').text_content() == 'No file selected'
        assert page.locator('[data-testid="source-kind"]').text_content() == '—'
        assert page.locator('[data-testid="health-state"]').text_content() == '—'
    finally:
        browser.close()
        playwright.stop()


def test_compare_ui_reports_invalid_modes_and_validation_errors(compare_server: str, tmp_path: Path) -> None:
    playwright, browser, page = _load_compare_page(compare_server)
    try:
        _load_fixture(page, HEALTHY_FIXTURE)
        page.evaluate("window.__compareArtifactRef = window.__compareState.artifact")

        page.evaluate("window.__setCompareMode('wireframe')")
        page.wait_for_function("document.querySelector('[data-testid=\"error-banner\"]').offsetParent !== null")
        error_text = page.locator('[data-testid="error-banner"]').text_content() or ''
        assert 'Unsupported compare mode "wireframe" fell back to side-by-side.' in error_text
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="compare-mode"]').text_content() == 'side-by-side'
        assert page.locator('[data-testid="compare-canvas"]').get_attribute('data-mode') == 'side-by-side'
        assert page.locator('[data-testid="status-banner"]').text_content() == 'Loaded artifact hidden while the error is shown.'
        assert page.locator('[data-testid="source-kind"]').text_content() == 'mp3'
        assert page.locator('[data-testid="health-state"]').text_content() == 'healthy'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3

        empty_stages_payload = json.loads(HEALTHY_FIXTURE.read_text(encoding='utf-8'))
        empty_stages_payload['metadata']['stages'] = []
        empty_stages_fixture = _write_temp_fixture(tmp_path, 'empty-stages.json', empty_stages_payload)
        page.set_input_files('#artifact-file', str(empty_stages_fixture))
        page.click('#load-button')
        page.wait_for_function("document.querySelector('[data-testid=\"error-banner\"]').textContent.includes('metadata.stages must contain at least one stage')")
        error_text = page.locator('[data-testid="error-banner"]').text_content() or ''
        assert 'metadata.stages must contain at least one stage' in error_text
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="status-banner"]').text_content() == 'Loaded artifact hidden while the error is shown.'
        assert page.locator('[data-testid="source-kind"]').text_content() == 'mp3'
        assert page.locator('[data-testid="health-state"]').text_content() == 'healthy'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3
        assert page.locator('[data-testid="compare-canvas"]').get_attribute('data-mode') == 'side-by-side'

        missing_stems_payload = json.loads(HEALTHY_FIXTURE.read_text(encoding='utf-8'))
        del missing_stems_payload['stem_paths']
        missing_stems_fixture = _write_temp_fixture(tmp_path, 'missing-stems.json', missing_stems_payload)
        page.set_input_files('#artifact-file', str(missing_stems_fixture))
        page.click('#load-button')
        page.wait_for_function("document.querySelector('[data-testid=\"error-banner\"]').textContent.includes('stem_paths must be an object')")
        error_text = page.locator('[data-testid="error-banner"]').text_content() or ''
        assert 'stem_paths must be an object' in error_text
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="status-banner"]').text_content() == 'Loaded artifact hidden while the error is shown.'
        assert page.locator('[data-testid="source-kind"]').text_content() == 'mp3'
        assert page.locator('[data-testid="health-state"]').text_content() == 'healthy'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3

        extra_stems_payload = json.loads(HEALTHY_FIXTURE.read_text(encoding='utf-8'))
        extra_stems_payload['stem_paths']['instrumental'] = 'artifacts/live/smoke/instrumental.wav'
        extra_stems_fixture = _write_temp_fixture(tmp_path, 'extra-stems.json', extra_stems_payload)
        page.set_input_files('#artifact-file', str(extra_stems_fixture))
        page.click('#load-button')
        page.wait_for_function("document.querySelector('[data-testid=\"error-banner\"]').textContent.includes('instrumental')")
        error_text = page.locator('[data-testid="error-banner"]').text_content() or ''
        assert 'stem_paths must contain exactly vocals, drums, bass, and other' in error_text
        assert 'instrumental' in error_text
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="status-banner"]').text_content() == 'Loaded artifact hidden while the error is shown.'
        assert page.locator('[data-testid="source-kind"]').text_content() == 'mp3'
        assert page.locator('[data-testid="health-state"]').text_content() == 'healthy'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3
    finally:
        browser.close()
        playwright.stop()


def test_compare_ui_rejects_legacy_stem_fixture_without_replacing_loaded_artifact(compare_server: str) -> None:
    playwright, browser, page = _load_compare_page(compare_server)
    try:
        _load_fixture(page, HEALTHY_FIXTURE)
        page.evaluate("window.__compareArtifactRef = window.__compareState.artifact")

        page.set_input_files("#artifact-file", str(MALFORMED_FIXTURE))
        page.click("#load-button")
        page.wait_for_function(
            "document.querySelector('[data-testid=\"error-banner\"]').offsetParent !== null"
        )

        error_banner = page.locator('[data-testid="error-banner"]')
        error_text = error_banner.text_content() or ""
        assert "Failed to parse or validate JSON artifact" in error_text
        assert "instrumental" in error_text
        assert "missing keys" in error_text
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="status-banner"]').text_content() == 'Loaded artifact hidden while the error is shown.'
        assert page.locator('[data-testid="source-kind"]').text_content() == "mp3"
        assert page.locator('[data-testid="health-state"]').text_content() == "healthy"
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3
    finally:
        browser.close()
        playwright.stop()


def test_compare_ui_rejects_malformed_json_without_replacing_loaded_artifact(compare_server: str, tmp_path: Path) -> None:
    playwright, browser, page = _load_compare_page(compare_server)
    try:
        _load_fixture(page, HEALTHY_FIXTURE)
        page.evaluate("window.__compareArtifactRef = window.__compareState.artifact")

        malformed_fixture = _write_temp_text_fixture(tmp_path, 'invalid-compare.json', '{"source": {"kind": "mp3"')
        page.set_input_files("#artifact-file", str(malformed_fixture))
        page.click("#load-button")
        page.wait_for_function(
            "document.querySelector('[data-testid=\"error-banner\"]').offsetParent !== null"
        )

        error_banner = page.locator('[data-testid="error-banner"]')
        error_text = error_banner.text_content() or ""
        assert "Failed to parse or validate JSON artifact" in error_text
        assert "Unexpected" in error_text or "JSON" in error_text
        assert page.evaluate("window.__compareArtifactRef === window.__compareState.artifact") is True
        assert page.locator('[data-testid="status-banner"]').text_content() == 'Loaded artifact hidden while the error is shown.'
        assert page.locator('[data-testid="source-kind"]').text_content() == "mp3"
        assert page.locator('[data-testid="health-state"]').text_content() == "healthy"
        assert page.locator('[data-testid="compare-stage-card"]').count() == 3
    finally:
        browser.close()
        playwright.stop()


def test_compare_ui_loads_evidence_manifest_and_calculates_benchmark_delta(compare_server: str, tmp_path: Path) -> None:
    manifest_path = _write_temp_fixture(
        tmp_path,
        "capstone-evidence.json",
        {
            "status": "ok",
            "phase": "complete",
            "execution_kinds": {
                "throughput_cpu": "cpu",
                "throughput_gpu": "gpu_pytorch",
            },
            "phases": [
                {
                    "name": "throughput_cpu",
                    "status": "ok",
                    "summary": {
                        "execution_kind": "cpu",
                        "wall_clock_ms_per_chunk": 120.0,
                        "throughput_chunks_per_second": 8.0,
                    },
                },
                {
                    "name": "throughput_gpu",
                    "status": "ok",
                    "summary": {
                        "execution_kind": "gpu_pytorch",
                        "wall_clock_ms_per_chunk": 30.0,
                        "throughput_chunks_per_second": 32.0,
                    },
                },
            ],
        },
    )

    playwright, browser, page = _load_compare_page(compare_server)
    try:
        page.set_input_files("#benchmark-file", str(manifest_path))
        page.click("#load-benchmark-button")
        page.wait_for_function("document.querySelector('[data-testid=\"benchmark-delta\"]').textContent === '4.00x'")

        assert page.locator('[data-testid="benchmark-kind-cpu"]').text_content() == "cpu"
        assert page.locator('[data-testid="benchmark-kind-gpu"]').text_content() == "gpu_pytorch"
        assert page.locator('[data-testid="benchmark-cpu-ms"]').text_content() == "120.00 ms"
        assert page.locator('[data-testid="benchmark-gpu-ms"]').text_content() == "30.00 ms"
        assert page.locator('[data-testid="benchmark-delta"]').text_content() == "4.00x"
    finally:
        browser.close()
        playwright.stop()


def test_compare_ui_loads_wav_stems_and_renders_waveform_lanes(compare_server: str, tmp_path: Path) -> None:
    input_wav = tmp_path / "input.wav"
    stem_paths = [
        tmp_path / "vocals.wav",
        tmp_path / "drums.wav",
        tmp_path / "bass.wav",
        tmp_path / "other.wav",
    ]
    _write_wav_fixture(input_wav, frequency_hz=220.0)
    for offset, stem_path in enumerate(stem_paths):
        _write_wav_fixture(stem_path, frequency_hz=330.0 + offset * 110.0)

    playwright, browser, page = _load_compare_page(compare_server)
    try:
        page.set_input_files("#input-audio-file", str(input_wav))
        page.set_input_files("#stem-audio-files", [str(path) for path in stem_paths])
        page.click("#load-audio-button")
        page.wait_for_function(
            "Array.from(document.querySelectorAll('[data-testid^=\"waveform-canvas-\"]')).every(canvas => canvas.dataset.rendered === 'true')"
        )

        assert page.locator('[data-testid="audio-file-count"]').text_content() == "5 files"
        for lane in ["input", "vocals", "drums", "bass", "other"]:
            assert page.locator(f'[data-testid="waveform-canvas-{lane}"]').get_attribute("data-rendered") == "true"
            pixel_total = page.evaluate(
                """lane => {
                  const canvas = document.querySelector(`[data-testid="waveform-canvas-${lane}"]`);
                  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
                  return Array.from(data).reduce((sum, value) => sum + value, 0);
                }""",
                lane,
            )
            assert pixel_total > 0
    finally:
        browser.close()
        playwright.stop()


def test_compare_ui_renders_dual_artifact_compare(compare_server: str) -> None:
    cpu_payload = json.loads(HEALTHY_FIXTURE.read_text(encoding='utf-8'))
    cpu_payload['metadata']['device_requested'] = 'cpu'
    cpu_payload['metadata']['device_used'] = 'cpu'
    cpu_payload['total_ms'] = 224.0
    cpu_payload['infer_ms'] = 180.0
    cpu_payload['stft_ms'] = 24.0
    cpu_payload['istft_ms'] = 20.0
    cpu_payload['timestamp'] = '2026-05-12T08:00:00Z'

    gpu_payload = json.loads(HEALTHY_FIXTURE.read_text(encoding='utf-8'))
    gpu_payload['metadata']['device_requested'] = 'gpu'
    gpu_payload['metadata']['device_used'] = 'gpu'
    gpu_payload['total_ms'] = 84.0
    gpu_payload['infer_ms'] = 54.0
    gpu_payload['stft_ms'] = 16.0
    gpu_payload['istft_ms'] = 14.0
    gpu_payload['timestamp'] = '2026-05-12T08:00:30Z'

    fixture_dir = PROJECT_ROOT / 'artifacts' / 'ui-compare-test'
    cpu_path = _write_project_fixture('artifacts/ui-compare-test/cpu-runtime.json', cpu_payload)
    gpu_path = _write_project_fixture('artifacts/ui-compare-test/gpu-runtime.json', gpu_payload)

    playwright, browser, page = _load_compare_page(compare_server)
    try:
        page.goto(
            f"{compare_server.rstrip('/')}/ui/compare/?artifact=/{cpu_path.relative_to(PROJECT_ROOT).as_posix()}"
            f"&artifact2=/{gpu_path.relative_to(PROJECT_ROOT).as_posix()}",
            wait_until="networkidle",
        )

        page.wait_for_function("document.querySelector('[data-testid=\"compare-dual-board\"]').offsetParent !== null")

        assert page.locator('[data-testid="compare-canvas"]').get_attribute('data-layout') == 'dual'
        assert page.locator('[data-testid="compare-dual-board"]').get_attribute('data-testid') == 'compare-dual-board'
        assert page.locator('[data-testid="compare-dual-columns"]').locator('[data-testid="compare-dual-column"]').count() == 2
        assert page.locator('[data-testid="compare-dual-left-role"]').text_content() == 'CPU'
        assert page.locator('[data-testid="compare-dual-right-role"]').text_content() == 'GPU'
        assert page.locator('[data-testid="compare-dual-left-total"]').text_content() == '224.00 ms total'
        assert page.locator('[data-testid="compare-dual-right-total"]').text_content() == '84.00 ms total'
        assert page.locator('[data-testid="compare-dual-speedup"]').text_content() == 'GPU is 2.7× faster'
        assert page.locator('[data-testid="compare-stage-card"]').count() == 6
        assert 'is-hidden' in (page.locator('[data-testid="final-stems-strip"]').get_attribute('class') or '')
    finally:
        browser.close()
        playwright.stop()
        shutil.rmtree(fixture_dir, ignore_errors=True)
