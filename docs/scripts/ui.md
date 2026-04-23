# UI Scripts

Scripts under `scripts/ui/` serve the static compare UI.

---

## `serve_compare_demo.py`

**Purpose:** Start a local HTTP server (Python `ThreadingHTTPServer`) rooted at the repository root (or a custom directory) and serve the vanilla-JS compare interface at `/ui/compare/`. The server logs all requests to stderr with a `compare-demo:` prefix.

**Invocation:**

```bash
python scripts/ui/serve_compare_demo.py [OPTIONS]
```

**Arguments:**

| Argument | Type | Default | Description |
|---|---|---|---|
| `--bind` | str | `127.0.0.1` | Interface to bind (use `0.0.0.0` to expose on the network) |
| `--port` | int | `8000` | TCP port to listen on |
| `--directory` | path | repository root | Directory to serve as the static web root |

**Outputs:**

- Stdout: `compare-demo: serving <directory> at http://<host>:<port>/ui/compare/` — printed immediately on start (flushed).
- Stderr: per-request access log lines prefixed with `compare-demo:`.
- Stderr: `compare-demo: shutdown requested` on `Ctrl+C`.
- Stderr: `compare-demo: stopped` after graceful shutdown.
- Stderr: `compare-demo: failed to bind <host>:<port> — <reason>` if the port is unavailable.

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Clean shutdown (Ctrl+C) |
| `2` | Directory not found or not a directory |
| `3` | Failed to bind address/port |

**Examples:**

```bash
# Default: serve repo root on localhost:8000
python scripts/ui/serve_compare_demo.py

# Custom port
python scripts/ui/serve_compare_demo.py --port 9000

# Expose on all interfaces
python scripts/ui/serve_compare_demo.py --bind 0.0.0.0 --port 8080

# Serve a specific directory
python scripts/ui/serve_compare_demo.py --directory /path/to/static
```

After starting, open `http://127.0.0.1:8000/ui/compare/` in a browser to access the comparison interface.

**Note:** This is a development server only. Do not expose it on a public interface in production.
