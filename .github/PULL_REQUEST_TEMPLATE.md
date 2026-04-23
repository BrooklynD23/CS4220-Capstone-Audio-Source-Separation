## Summary

<!-- Describe what this PR does and why. -->

## Changes

<!-- Bullet list of the key changes made. -->

- 

## Testing

<!-- Describe how you tested this. Check all that apply. -->

- [ ] `pytest` passes locally
- [ ] Ran `bash scripts/verify/s01_check.sh` (or relevant verifier)
- [ ] Tested with `--dry-run` (CI-safe, no GPU required)
- [ ] GPU path tested (if applicable)
- [ ] UI smoke test (`python scripts/ui/serve_compare_demo.py`)

## Artifacts

<!-- If this PR produces or changes artifact schemas, paste a sample here. -->

<details>
<summary>Sample artifact (optional)</summary>

```json

```

</details>

## Checklist

- [ ] Code follows the project conventions (immutable patterns, small files, no hardcoded paths)
- [ ] Tests added or updated for changed behavior
- [ ] No hardcoded secrets or API keys
- [ ] `artifacts/` outputs are not committed (gitignored)
- [ ] `configs/environment.lock.md` updated if environment assumptions changed
