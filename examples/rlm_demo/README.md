# RLM Demo: Recursive Language Model Pattern with Output Caching

This example demonstrates the **Recursive Language Model (RLM)** pattern using
easy-mcp-proxy's output caching feature. It compares two approaches to
processing large tool outputs:

1. **Direct approach**: The LLM receives the full log data in its context
2. **RLM approach**: The LLM receives a cached reference, delegates to a sub-agent

## Prerequisites

- Python 3.11+
- Docker (for sub-agent sandbox)
- OpenAI API key

## Setup

```bash
cd examples/rlm_demo
pip install -r requirements.txt

# Build the sub-agent container
docker build -t rlm-subagent .

# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."
```

## Running the Experiment

```bash
# Generate a ~150KB log file with random data and errors
python generate_logs.py

# Run the comparison experiment
python run_experiment.py
```

## What It Does

### 1. Generate Logs (`generate_logs.py`)

Creates `logs.ndjson` — a ~150KB file of newline-delimited JSON log entries:
- Random INFO, DEBUG, WARN entries with realistic payloads
- Interspersed ERROR and FATAL entries for the agent to find
- Approximately 40,000 tokens when loaded raw

### 2. Custom Tool (`log_tools.py`)

A `@custom_tool` decorated function `get_logs()` that reads and returns the
log file contents. The proxy exposes this tool twice:
- **Raw view**: Returns full content (no caching)
- **Cached view**: Returns preview + signed URL

### 3. Run Experiment (`run_experiment.py`)

Compares token usage between approaches:

| Phase | Direct Approach | RLM Approach |
|-------|-----------------|--------------|
| Tool call | LLM receives ~40K tokens | LLM receives ~200 tokens |
| Processing | LLM analyzes inline | Sub-agent fetches & processes |
| Final result | Full context consumed | Minimal tokens returned |

## Expected Output

```
============================================================
RLM PATTERN DEMO: Context Efficiency Comparison
============================================================

Generated log file: logs.ndjson (153,248 bytes)

--- DIRECT APPROACH (no caching) ---
Tool output tokens: 41,234
LLM response tokens: 847
Total context used: 42,081 tokens

--- RLM APPROACH (cached output) ---
Cached response tokens: 187
Sub-agent processed: 153,248 bytes
Sub-agent output tokens: 234
Total context used: 421 tokens

============================================================
RESULT: RLM approach used 99.0% fewer tokens
============================================================
```

## How the RLM Pattern Works

```
┌─────────────────────────────────────────────────────────────┐
│ DIRECT APPROACH                                             │
├─────────────────────────────────────────────────────────────┤
│ User → LLM: "Analyze the logs"                              │
│ LLM → Tool: get_logs()                                      │
│ Tool → LLM: [150KB of JSON data] ← Context stuffed!         │
│ LLM → User: "Here's what I found..." (limited reasoning)    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ RLM APPROACH                                                │
├─────────────────────────────────────────────────────────────┤
│ User → LLM: "Analyze the logs"                              │
│ LLM → Tool: get_logs()                                      │
│ Tool → LLM: {preview, token, retrieve_url} ← Minimal!       │
│ LLM → Sub-agent: "Fetch URL, extract ERROR entries"         │
│ Sub-agent: curl URL | jq 'select(.level=="ERROR")'          │
│ Sub-agent → LLM: [structured summary, ~200 tokens]          │
│ LLM → User: "Here's the analysis..." (full reasoning)       │
└─────────────────────────────────────────────────────────────┘
```

## Files

- `generate_logs.py` — Creates the test log file
- `log_tools.py` — Custom MCP tool returning log data
- `run_experiment.py` — Main driver comparing both approaches
- `Dockerfile` — Sub-agent container (Python, jq, curl, tiktoken)
- `requirements.txt` — Python dependencies

