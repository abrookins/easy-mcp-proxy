# Sub-agent container for RLM demo
# Provides Python, jq, and curl for processing cached tool outputs

FROM python:3.11-slim

# Install jq and curl
RUN apt-get update && \
    apt-get install -y --no-install-recommends jq curl && \
    rm -rf /var/lib/apt/lists/*

# Install tiktoken for token counting (optional, for verification)
RUN pip install --no-cache-dir tiktoken

# Set working directory
WORKDIR /work

# Default command (will be overridden)
CMD ["python", "--version"]

