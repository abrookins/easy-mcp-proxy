#!/usr/bin/env python3
"""Generate a large NDJSON log file for RLM pattern demonstration.

Creates ~150KB of newline-delimited JSON log entries with:
- Random INFO, DEBUG, WARN entries
- Interspersed ERROR and FATAL entries
- Realistic timestamps and payloads
"""

import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
OUTPUT_FILE = Path(__file__).parent / "logs.ndjson"
TARGET_SIZE_KB = 150
ERROR_RATIO = 0.05  # 5% of entries are errors

# Sample data for realistic logs
SERVICES = [
    "api-gateway",
    "auth-service",
    "user-service",
    "payment-service",
    "inventory",
]
ENDPOINTS = [
    "/api/v1/users",
    "/api/v1/orders",
    "/api/v1/products",
    "/health",
    "/metrics",
]
ERROR_MESSAGES = [
    "Connection timeout to database",
    "Database deadlock detected",
    "Out of memory exception",
    "Rate limit exceeded",
    "Authentication failed",
    "Invalid request payload",
    "Service unavailable",
    "Circuit breaker open",
    "Cache miss for critical key",
    "SSL certificate expired",
]
INFO_MESSAGES = [
    "Request processed successfully",
    "Cache hit for user data",
    "Connection pool refreshed",
    "Metrics exported",
    "Health check passed",
    "Session created",
    "Token refreshed",
    "Batch job started",
    "Configuration reloaded",
]


def generate_log_entry(timestamp: datetime, force_error: bool = False) -> dict:
    """Generate a single log entry."""
    is_error = force_error or random.random() < ERROR_RATIO
    level = (
        random.choice(["ERROR", "FATAL"])
        if is_error
        else random.choice(
            ["INFO", "INFO", "INFO", "DEBUG", "WARN"]  # Weighted toward INFO
        )
    )

    service = random.choice(SERVICES)
    request_id = str(uuid.uuid4())[:8]

    entry = {
        "timestamp": timestamp.isoformat() + "Z",
        "level": level,
        "service": service,
        "request_id": request_id,
    }

    if is_error:
        entry["message"] = random.choice(ERROR_MESSAGES)
        entry["error_code"] = random.randint(1000, 9999)
        line_num = random.randint(50, 500)
        entry["stack_trace"] = f"at {service}.Handler.process(Handler.java:{line_num})"
    else:
        entry["message"] = random.choice(INFO_MESSAGES)
        entry["endpoint"] = random.choice(ENDPOINTS)
        entry["duration_ms"] = random.randint(1, 500)
        entry["user_id"] = f"user_{random.randint(1000, 9999)}"

    # Add some random metadata to vary entry sizes
    if random.random() > 0.7:
        major, minor, patch = (
            random.randint(1, 5),
            random.randint(0, 20),
            random.randint(0, 100),
        )
        entry["metadata"] = {
            "region": random.choice(["us-east-1", "us-west-2", "eu-west-1"]),
            "instance": f"i-{uuid.uuid4().hex[:8]}",
            "version": f"v{major}.{minor}.{patch}",
        }

    return entry


def generate_logs():
    """Generate the log file."""
    print(f"Generating logs targeting ~{TARGET_SIZE_KB}KB...")

    entries = []
    current_size = 0
    target_bytes = TARGET_SIZE_KB * 1024

    # Start from a random time in the past 24 hours
    base_time = datetime.now() - timedelta(hours=24)
    current_time = base_time

    while current_size < target_bytes:
        # Advance time by 1-60 seconds
        current_time += timedelta(seconds=random.randint(1, 60))

        entry = generate_log_entry(current_time)
        line = json.dumps(entry, separators=(",", ":"))  # Compact JSON
        entries.append(line)
        current_size += len(line) + 1  # +1 for newline

    # Write to file
    OUTPUT_FILE.write_text("\n".join(entries) + "\n")

    # Count errors
    error_count = sum(1 for e in entries if '"ERROR"' in e or '"FATAL"' in e)

    print(f"Generated: {OUTPUT_FILE}")
    print(f"  Size: {OUTPUT_FILE.stat().st_size:,} bytes")
    print(f"  Entries: {len(entries):,}")
    print(f"  Errors: {error_count:,} ({100 * error_count / len(entries):.1f}%)")


if __name__ == "__main__":
    generate_logs()
