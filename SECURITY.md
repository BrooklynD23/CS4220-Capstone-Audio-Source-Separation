# Security Policy

## Supported Versions

This is an academic capstone project. Security patches are applied to the latest version only.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

### How to Report

Send a report to: **ledangquocbao3006@gmail.com**

Include the following in your report:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact assessment
- Any suggested mitigations (optional)

### Response Timeline

- **Acknowledgement**: Within 48 hours of receiving your report
- **Status update**: Within 7 days with an assessment of the issue
- **Resolution**: Best-effort basis given the academic nature of this project

## Scope

This project is a reproducible evaluation and benchmarking harness for audio source separation models (UMX/Demucs). The following areas are in scope:

- Arbitrary file write via crafted audio input paths
- Command injection in shell scripts under `scripts/`
- Path traversal in artifact output handling
- Unsafe deserialization of model files or JSON artifacts
- Dependency vulnerabilities in `pyproject.toml` dependencies

The following are **out of scope**:

- Vulnerabilities in third-party ML model weights (UMX, Demucs)
- GPU driver or TensorRT security issues
- Issues requiring physical access to the machine

## Security Considerations for Contributors

When contributing to this project:

- **Input validation**: Validate all file paths before use; do not pass user-supplied paths directly to shell commands.
- **No secrets in code**: Never commit API keys, credentials, or tokens. Use environment variables.
- **Dependency pinning**: Dependencies are pinned in `pyproject.toml`. Update them via Dependabot PRs, not ad-hoc edits.
- **Artifact paths**: All generated outputs must resolve under the `artifacts/` directory. Reject paths that escape this boundary.
- **Model loading**: Only load model files from the trusted `artifacts/models/` directory.

## Known Security Assumptions

This project operates under the following explicit trust assumptions documented in `configs/environment.lock.md`:

- Model weight files (`.pt`) are sourced from trusted, reproducible checkpoints.
- Audio input files (MP3, WAV, video) are treated as untrusted and processed in isolated temporary directories.
- The evaluation harness runs in a controlled CI environment; network access is not required at runtime.
