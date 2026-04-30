"""Local monitor page for the Codex WeChat bridge."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
for path in (APP_ROOT, APP_ROOT / "workflows"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bridge_loop import DEFAULT_CONFIG_PATH, load_config, load_state  # noqa: E402
from task_ledger import build_monitor_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    monitor = dict(config.get("monitor") or {})
    host = args.host or str(monitor.get("host") or "127.0.0.1")
    port = int(args.port or monitor.get("port") or 17911)

    handler = make_handler(config)
    server = ThreadingHTTPServer((host, port), handler)
    start_epoch = time.time()
    threading.Thread(
        target=watch_shutdown_request,
        args=(server, config, start_epoch),
        daemon=True,
    ).start()
    print(f"Codex WeChat Bridge monitor: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def watch_shutdown_request(server: ThreadingHTTPServer, config: dict[str, Any], start_epoch: float) -> None:
    while True:
        try:
            state = load_state(config)
            shutdown_at = float(state.get("shutdown_requested_at") or 0)
            if shutdown_at > start_epoch:
                server.shutdown()
                return
        except Exception:
            pass
        time.sleep(1)


def make_handler(config: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    class MonitorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route in {"/", "/index.html"}:
                self.write_text(index_html(), content_type="text/html; charset=utf-8")
                return
            if route == "/api/status":
                snapshot = build_monitor_snapshot(config, bridge_state=load_state(config))
                self.write_json(snapshot)
                return
            self.send_error(404, "Not found")

        def log_message(self, format: str, *args: Any) -> None:
            return

        def write_json(self, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def write_text(self, text: str, *, content_type: str) -> None:
            data = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return MonitorHandler


def index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex WeChat Bridge Monitor</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: Segoe UI, Arial, sans-serif;
      background: #f6f7f9;
      color: #1f2933;
    }
    body { margin: 0; }
    header {
      padding: 18px 22px;
      border-bottom: 1px solid #d5d9df;
      background: #ffffff;
    }
    h1 { margin: 0; font-size: 20px; font-weight: 650; }
    main { padding: 18px 22px 32px; display: grid; gap: 16px; }
    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
    .panel {
      background: #ffffff;
      border: 1px solid #d5d9df;
      border-radius: 8px;
      padding: 14px;
    }
    .label { color: #5b6673; font-size: 12px; text-transform: uppercase; }
    .value { margin-top: 6px; font-size: 15px; overflow-wrap: anywhere; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { border-bottom: 1px solid #e2e6ea; padding: 9px 8px; text-align: left; vertical-align: top; }
    th { color: #5b6673; font-size: 12px; text-transform: uppercase; }
    code { font-family: Consolas, monospace; }
    .status { font-weight: 650; }
    .done { color: #147d45; }
    .running, .queued, .codex_completed { color: #8a5a00; }
    .failed, .send_failed { color: #b42318; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
    @media (prefers-color-scheme: dark) {
      :root { background: #11161d; color: #e5e7eb; }
      header, .panel { background: #171d25; border-color: #2d3743; }
      th, td { border-color: #2d3743; }
      .label, th { color: #98a2b3; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Codex WeChat Bridge Monitor</h1>
  </header>
  <main>
    <section class="summary">
      <div class="panel"><div class="label">Generated</div><div id="generated" class="value">loading</div></div>
      <div class="panel"><div class="label">Active Thread</div><div id="thread" class="value">loading</div></div>
      <div class="panel"><div class="label">Latest Run</div><div id="latest" class="value">loading</div></div>
      <div class="panel"><div class="label">Pending Reply</div><div id="pending" class="value">loading</div></div>
      <div class="panel"><div class="label">Last Poll</div><div id="lastPoll" class="value">loading</div></div>
    </section>
    <section class="panel">
      <table>
        <thead><tr><th>Run</th><th>Status</th><th>Prompt</th><th>Thread / Turn</th><th>Updated</th></tr></thead>
        <tbody id="runs"></tbody>
      </table>
    </section>
    <section class="panel">
      <div class="label">Desktop Index</div>
      <pre id="desktop">loading</pre>
    </section>
  </main>
  <script>
    const text = (id, value) => { document.getElementById(id).textContent = value ?? ""; };
    const esc = (value) => String(value ?? "").replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
    async function refresh() {
      const res = await fetch("/api/status", { cache: "no-store" });
      const data = await res.json();
      text("generated", data.generated_at);
      text("thread", data.active_thread_id || "(none)");
      text("latest", data.latest_run ? `${data.latest_run.run_id} / ${data.latest_run.status}` : "(none)");
      text("pending", data.pending_reply ? "yes" : "no");
      text("lastPoll", data.last_poll ? `${data.last_poll.at} / ok=${data.last_poll.ok} / new=${data.last_poll.new_count}` : "(none)");
      text("desktop", JSON.stringify(data.desktop_index || {}, null, 2));
      const rows = (data.runs || []).map(run => `
        <tr>
          <td><code>${esc(run.run_id)}</code></td>
          <td class="status ${esc(run.status)}">${esc(run.status)}</td>
          <td>${esc(run.prompt_preview || run.prompt || "")}</td>
          <td><code>${esc(run.thread_id || "")}</code><br><code>${esc(run.turn_id || "")}</code></td>
          <td>${esc(run.updated_at || run.created_at || "")}</td>
        </tr>`).join("");
      document.getElementById("runs").innerHTML = rows || '<tr><td colspan="5">No runs yet.</td></tr>';
    }
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
