#!/usr/bin/env python3
"""RLM Pattern Demo: Compare direct vs. cached output approaches.

This script demonstrates the context efficiency of the Recursive Language Model
pattern by comparing:
1. Direct approach: LLM receives full tool output in context
2. RLM approach: LLM receives cached reference, delegates to sub-agent

Requirements:
- OpenAI API key (OPENAI_API_KEY environment variable)
- Docker (for sub-agent container)
- Generated logs (run generate_logs.py first)
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import tiktoken
from openai import OpenAI

# Add parent dirs to path for mcp_proxy imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load .env file from repo root
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)

# Configuration
LOG_FILE = Path(__file__).parent / "logs.ndjson"
CACHE_SECRET = "demo-secret-key-for-rlm-experiment"
CACHE_BASE_URL = "http://host.docker.internal:8765"  # Docker can reach host
OPENAI_MODEL = "gpt-4o-mini"  # Cost-effective for demo

# Token counter
ENCODER = tiktoken.encoding_for_model("gpt-4o")


def count_tokens(text: str) -> int:
    """Count tokens in a string."""
    return len(ENCODER.encode(text))


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


async def run_direct_approach(client: OpenAI) -> dict:
    """Run the direct approach: LLM receives full log data."""
    print("\n--- DIRECT APPROACH (no caching) ---")

    # Read the raw log content (simulating what the tool would return)
    log_content = LOG_FILE.read_text()
    log_tokens = count_tokens(log_content)
    print(f"Log file tokens: {log_tokens:,}")

    # Call the LLM with the full log data
    messages = [
        {
            "role": "system",
            "content": "You are analyzing application logs. Be concise.",
        },
        {
            "role": "user",
            "content": f"""Analyze these logs and summarize the error patterns:

{log_content}

Return a JSON object with:
- error_count: total errors
- patterns: array of {{pattern, count, severity}}""",
        },
    ]

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=500,
    )

    response_text = response.choices[0].message.content
    response_tokens = count_tokens(response_text)

    print(f"LLM response tokens: {response_tokens:,}")
    print(f"Total context used: {log_tokens + response_tokens:,} tokens")

    return {
        "input_tokens": log_tokens,
        "output_tokens": response_tokens,
        "total_tokens": log_tokens + response_tokens,
        "response": response_text,
    }


async def run_rlm_approach(client: OpenAI, retrieve_url: str) -> dict:
    """Run the RLM approach: LLM delegates to sub-agent."""
    print("\n--- RLM APPROACH (cached output) ---")

    # Simulated cached response (what the tool would return with caching)
    log_content = LOG_FILE.read_text()
    preview = log_content[:500] + "..."
    cached_response = {
        "cached": True,
        "preview": preview,
        "retrieve_url": retrieve_url,
        "size_bytes": len(log_content.encode()),
    }

    cached_response_str = json.dumps(cached_response, indent=2)
    cached_tokens = count_tokens(cached_response_str)
    print(f"Cached response tokens: {cached_tokens:,}")

    # Step 1: Parent LLM decides to delegate
    # (In real usage, the LLM would spawn a sub-agent; we simulate this)
    print("Parent LLM delegating to sub-agent...")

    # Step 2: Sub-agent processes the data (runs in Docker)
    subagent_result = run_subagent(retrieve_url)
    subagent_tokens = count_tokens(subagent_result)
    print(f"Sub-agent output tokens: {subagent_tokens:,}")

    # Step 3: Parent LLM receives sub-agent's summary
    messages = [
        {
            "role": "system",
            "content": "You are analyzing a summary of application logs.",
        },
        {
            "role": "user",
            "content": f"""A sub-agent analyzed the logs and returned:

{subagent_result}

Provide a brief executive summary of the error patterns.""",
        },
    ]

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=300,
    )

    response_text = response.choices[0].message.content
    response_tokens = count_tokens(response_text)

    total = cached_tokens + subagent_tokens + response_tokens
    print(f"LLM final response tokens: {response_tokens:,}")
    print(f"Total context used: {total:,} tokens")

    return {
        "cached_tokens": cached_tokens,
        "subagent_tokens": subagent_tokens,
        "output_tokens": response_tokens,
        "total_tokens": total,
        "response": response_text,
    }


def run_subagent(retrieve_url: str) -> str:
    """Run the sub-agent in Docker to process log data.

    The sub-agent:
    1. Fetches the cached data via curl
    2. Processes with jq to extract error patterns
    3. Returns a structured summary
    """
    # jq script to extract and summarize errors
    jq_script = """
    [.[] | select(.level == "ERROR" or .level == "FATAL")]
    | group_by(.message | split(" ")[0:3] | join(" "))
    | map({
        pattern: .[0].message,
        count: length,
        level: .[0].level,
        first_seen: (sort_by(.timestamp) | first | .timestamp),
        last_seen: (sort_by(.timestamp) | last | .timestamp)
      })
    | sort_by(-.count)
    """

    # Build the command to run in Docker
    cmd = [
        "docker",
        "run",
        "--rm",
        "--add-host=host.docker.internal:host-gateway",
        "rlm-subagent",
        "sh",
        "-c",
        f"curl -s \"{retrieve_url}\" | jq -s '{jq_script}'",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return json.dumps({"error": result.stderr or "Sub-agent failed"})
        return result.stdout
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Sub-agent timed out"})
    except FileNotFoundError:
        return json.dumps({"error": "Docker not found. Is it installed?"})


async def start_cache_server() -> subprocess.Popen:
    """Start a simple HTTP server for cache retrieval."""
    from mcp_proxy.cache import CACHE_DIR, create_cached_output_with_meta

    # Create the cached file
    log_content = LOG_FILE.read_text()
    cached = create_cached_output_with_meta(
        content=log_content,
        secret=CACHE_SECRET,
        base_url=CACHE_BASE_URL,
        ttl_seconds=3600,
        preview_chars=500,
    )

    # Extract the URL parts for serving
    # The cache is stored in CACHE_DIR/{token}.txt
    print(f"Cache stored at: {CACHE_DIR}/{cached.token}.txt")
    print(f"Retrieve URL: {cached.retrieve_url}")

    # Start a simple HTTP server to serve the cache
    # (In production, the proxy's http_app handles this)
    server_script = f'''
import http.server
import socketserver
from pathlib import Path

CACHE_DIR = Path("{CACHE_DIR}")

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Parse /cache/{{token}}?expires=...&sig=...
        if self.path.startswith("/cache/"):
            token = self.path.split("/cache/")[1].split("?")[0]
            cache_file = CACHE_DIR / f"{{token}}.txt"
            if cache_file.exists():
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(cache_file.read_bytes())
                return
        self.send_response(404)
        self.end_headers()

with socketserver.TCPServer(("", 8765), Handler) as httpd:
    httpd.serve_forever()
'''

    # Start server in background
    proc = subprocess.Popen(
        [sys.executable, "-c", server_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to start
    await asyncio.sleep(1)
    return proc, cached.retrieve_url


async def main():
    """Run the RLM pattern comparison experiment."""
    print_header("RLM PATTERN DEMO: Context Efficiency Comparison")

    # Check prerequisites
    if not LOG_FILE.exists():
        print(f"Error: {LOG_FILE} not found. Run generate_logs.py first.")
        sys.exit(1)

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        sys.exit(1)

    log_size = LOG_FILE.stat().st_size
    print(f"\nLog file: {LOG_FILE.name} ({log_size:,} bytes)")

    # Initialize OpenAI client
    client = OpenAI()

    # Start cache server
    print("\nStarting cache server...")
    server_proc, retrieve_url = await start_cache_server()

    try:
        # Run both approaches
        direct_result = await run_direct_approach(client)
        rlm_result = await run_rlm_approach(client, retrieve_url)

        # Print comparison
        print_header("RESULTS")
        ratio = rlm_result["total_tokens"] / direct_result["total_tokens"]
        reduction = (1 - ratio) * 100
        print(f"\nDirect approach: {direct_result['total_tokens']:,} tokens")
        print(f"RLM approach: {rlm_result['total_tokens']:,} tokens")
        print(f"\n✓ RLM approach used {reduction:.1f}% fewer tokens")

    finally:
        server_proc.terminate()
        server_proc.wait()


if __name__ == "__main__":
    asyncio.run(main())
