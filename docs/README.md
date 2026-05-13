# Documentation index

Welcome to the capstone harness documentation. Use this page as a map; the **[root README](../README.md)** is the primary handoff overview with architecture diagrams.

## Start here

1. **[README](../README.md)** — project purpose, diagrams, quick start, verifier commands  
2. **[Architecture diagrams](architecture/README.md)** — Mermaid class/component/sequence views  
3. **[Operations runbook](ops/RUNBOOK.md)** — day-two commands and failure triage  

## Reference

| Section | Contents |
|---------|----------|
| **[API (`live_runtime`)](api/README.md)** | Contracts, ingest, `live_core`, `stem_router`, optional `umx_separator` |
| **[Scripts](scripts/README.md)** | Eval, export, benchmarks, live CLI, UI server, validators |
| **[Compare UI](ui/README.md)** | Preload/query params, `POST /api/separate`, WAV/mix semantics, Playwright IDs |
| **[Tests](tests/README.md)** | Layout, fixtures, pytest / Playwright, coverage expectations |
| **[Configuration & schemas](config/README.md)** | `pyproject.toml`, pytest coverage defaults, artifact JSON schemas |
| **[environment.lock](../configs/environment.lock.md)** | Reproducibility pins and verifier assumptions |

## Reports & history

| Item | Path |
|------|------|
| Intermediate → capstone progress narrative | [`reports/CAPSTONE_PROGRESS_REPORT.md`](reports/CAPSTONE_PROGRESS_REPORT.md) |
| Formal proposal PDF | [`reports/CS4220_FINAL_PROJECT_PROPOSAL.pdf`](reports/CS4220_FINAL_PROJECT_PROPOSAL.pdf) |

## Internal / archived

Agent-authored planning specs (not authoritative product docs): **[`archive/README.md`](archive/README.md)**.
