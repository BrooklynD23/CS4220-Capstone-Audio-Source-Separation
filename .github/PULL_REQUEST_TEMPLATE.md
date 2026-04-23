## Summary

<!-- Describe what this PR does and why. -->

## Changes

- 
- 

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / cleanup
- [ ] Documentation
- [ ] CI / tooling
- [ ] Tests

## Testing

<!-- Describe how you tested these changes. -->

- [ ] `pytest` passes locally
- [ ] Relevant slice verifiers run (e.g. `bash scripts/verify/s01_check.sh`)
- [ ] Dry-run ONNX export verified (if export path touched)
- [ ] No GPU-only code added without a `--dry-run` fallback

## Checklist

- [ ] Code follows project conventions (`CLAUDE.md`)
- [ ] No hardcoded secrets or credentials
- [ ] New tests added / existing tests updated
- [ ] `artifacts/` outputs not committed (they are gitignored)
- [ ] JSON schema contracts unbroken (status + error_stage fields preserved)
