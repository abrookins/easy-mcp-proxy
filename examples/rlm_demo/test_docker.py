#!/usr/bin/env python3
"""Test the Docker sub-agent can fetch cached data."""

import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer

import tiktoken

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp_proxy.cache import CACHE_DIR, create_cached_output_with_meta

# Create cached file
content = Path(__file__).parent.joinpath("logs.ndjson").read_text()
cached = create_cached_output_with_meta(
    content=content,
    secret="demo-secret",
    base_url="http://host.docker.internal:8765",
    ttl_seconds=3600,
    preview_chars=500,
)
print(f"Cache token: {cached.token}")
print(f"Cache file: {CACHE_DIR}/{cached.token}.txt")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/cache/"):
            token = self.path.split("/cache/")[1].split("?")[0]
            cache_file = CACHE_DIR / f"{token}.txt"
            if cache_file.exists():
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(cache_file.read_bytes())
                return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


server = TCPServer(("", 8765), Handler)
thread = threading.Thread(target=server.serve_forever)
thread.daemon = True
thread.start()
print("Server started on port 8765")
time.sleep(1)

# Test Docker can fetch
jq_script = """
[.[] | select(.level == "ERROR" or .level == "FATAL")]
| group_by(.message | split(" ")[0:3] | join(" "))
| map({pattern: .[0].message, count: length, level: .[0].level})
| sort_by(-.count)
"""

cmd = [
    "docker",
    "run",
    "--rm",
    "--add-host=host.docker.internal:host-gateway",
    "rlm-subagent",
    "sh",
    "-c",
    f"curl -s '{cached.retrieve_url}' | jq -s '{jq_script}'",
]

print("Running Docker sub-agent...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
if result.returncode != 0:
    print(f"Error: {result.stderr}")
    sys.exit(1)

print("Sub-agent output:")
print(result.stdout)

# Count tokens
enc = tiktoken.encoding_for_model("gpt-4o")
subagent_tokens = len(enc.encode(result.stdout))
log_tokens = len(enc.encode(content))

print("\n=== Token Comparison ===")
print(f"Full log data: {log_tokens:,} tokens")
print(f"Sub-agent summary: {subagent_tokens:,} tokens")
print(f"Reduction: {(1 - subagent_tokens / log_tokens) * 100:.1f}%")

server.shutdown()
