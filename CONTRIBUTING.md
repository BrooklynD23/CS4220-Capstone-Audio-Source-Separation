# Contributing to CS4220 Capstone — Audio Source Separation

Thank you for your interest in contributing! This document outlines the process for contributing to this reproducible evaluation and benchmarking harness for audio source separation models.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Code Style](#code-style)
- [Testing](#testing)
- [Commit Messages](#commit-messages)
- [Pull Request Process](#pull-request-process)
- [Reporting Issues](#reporting-issues)

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/CS4220-Capstone-Audio-Source-Separation.git
   cd CS4220-Capstone-Audio-Source-Separation
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/ORIGINAL_OWNER/CS4220-Capstone-Audio-Source-Separation.git
   ```

## Development Setup

**Requirements:** Python `>=3.10,<3.15`

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
.venv\Scripts\activate          # Windows

# Install core dependencies + dev extras
pip install -e .[dev]

# Optional: microphone capture support (requires PortAudio)
pip install -e .[mic]
```

## How to Contribute

### Branching Strategy

Create a feature branch from `main`:

```bash
git checkout main
git pull upstream main
git checkout -b feat/your-feature-name
```

Use descriptive branch names prefixed with:
- `feat/` — new features
- `fix/` — bug fixes
- `docs/` — documentation changes
- `refactor/` — code refactoring
- `test/` — test additions or fixes
- `chore/` — maintenance tasks

### Workflow

1. Make your changes in small, focused commits
2. Write or update tests for any changed behavior
3. Run the full test suite locally before opening a PR
4. Verify slice contracts pass (see [Testing](#testing))

## Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions
- Keep functions small and focused
- Use descriptive variable and function names
- Avoid mutating existing objects — return new ones instead
- Validate all inputs at system boundaries (user input, file I/O, external data)
- Handle errors explicitly — do not silently swallow exceptions
- Keep files under 800 lines; prefer many small focused files

## Testing

All contributions must include tests. This project uses `pytest`.

```bash
# Run full test suite
pytest

# Run with coverage report
pytest --cov=live_runtime --cov=scripts -v

# Run slice verifiers (CI-safe, no GPU required)
bash scripts/verify/s01_check.sh       # ONNX export + schema
bash scripts/verify/s02_check.sh       # Live MP3 → four-stem
bash scripts/verify/m002_s01_check.sh  # Demucs live-runtime contract
bash scripts/verify/s06_check.sh       # Final capstone evidence bundle
```

**Test conventions:**
- Test files are named `test_*.py` under `tests/`
- Mirror the `scripts/` / `live_runtime/` directory structure under `tests/`
- Dry-run and contract tests must not require GPU or real model weights
- Target ≥80% code coverage for any modified modules

### GPU / CI Notes

- All slice verifiers support `--dry-run` for CI environments without a GPU
- `trtexec` must be on `PATH` for TRT engine builds; CUDA and TensorRT versions must match the driver stack
- ONNX export targets opset 17 (minimum 13); only the sample dimension may vary dynamically
- See `configs/environment.lock.md` for full reproducibility assumptions

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

**Examples:**
```
feat(ingest): add video frame extraction via ffmpeg
fix(contracts): preserve error_stage field on failed runs
docs(readme): update S06 evidence bundle instructions
test(runtime): add dry-run contract for Demucs path
```

Keep the subject line under 72 characters. Use the body to explain *why*, not *what*.

## Pull Request Process

1. Ensure all tests pass locally, including slice verifiers
2. Update relevant documentation if your change affects behavior
3. Open a PR against the `main` branch with a clear title and description
4. Reference any related issues with `Closes #<issue-number>` in the PR body
5. A project maintainer will review your PR; address any requested changes
6. Once approved, your PR will be merged

### PR Description Template

```markdown
## Summary
- What does this PR do?

## Motivation
- Why is this change needed?

## Test Plan
- [ ] Unit tests added/updated
- [ ] Integration/slice verifier passes
- [ ] No GPU-dependent tests added without a dry-run fallback
```

## Reporting Issues

Use the GitHub Issues tracker. When filing a bug report, please include:

- A clear description of the issue
- Steps to reproduce
- Expected vs. actual behavior
- Python version and OS
- Relevant log output or error messages
- Whether you are running in GPU or dry-run mode

For feature requests, describe the use case and expected behavior clearly.

## License

By contributing, you agree that your contributions will be licensed under the same license as this project.
