"""MFCQI code quality analysis tool."""

import asyncio

from mcp_proxy.custom_tools import custom_tool


@custom_tool(
    name="analyze_code_quality",
    description="""Analyze code quality using MFCQI (Multi-Factor Code Quality Index).

Returns comprehensive metrics including:
- Cyclomatic & Cognitive Complexity
- Halstead Volume
- Maintainability Index
- Code Duplication
- Documentation Coverage
- Security Score
- Dependency Security
- Secrets Exposure
- Code Smell Density
- OOP Metrics: RFC, DIT, MHF, CBO, LCOM

Use this to assess code quality, identify areas for improvement, or validate
that code meets quality thresholds before merging.

By default runs in metrics-only mode (no LLM).
Set skip_llm=False to get AI recommendations.""",
)
async def analyze_code_quality(
    project_path: str,
    min_score: float = 0.7,
    skip_llm: bool = True,
    output_format: str = "terminal",
    quality_gate: bool = False,
    recommendations: int = 5,
) -> dict:
    """Run MFCQI analysis on a codebase.

    Args:
        project_path: Absolute path to the project directory to analyze (required)
        min_score: Minimum acceptable MFCQI score threshold (default: 0.7)
        skip_llm: Skip LLM analysis, metrics only (default: True)
        output_format: Output format - terminal, json, html, markdown, sarif
        quality_gate: Enable quality gates (exit 1 if gates fail)
        recommendations: Number of AI recommendations to generate (if LLM enabled)

    Returns:
        Analysis results including metrics breakdown and overall score
    """
    cmd = ["uvx", "mfcqi", "analyze", project_path]

    if min_score:
        cmd.extend(["--min-score", str(min_score)])

    if skip_llm:
        cmd.append("--skip-llm")

    if output_format and output_format != "terminal":
        cmd.extend(["--format", output_format])

    if quality_gate:
        cmd.append("--quality-gate")

    if not skip_llm and recommendations:
        cmd.extend(["--recommendations", str(recommendations)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    output = stdout.decode()
    error_output = stderr.decode()

    return {
        "output": output,
        "stderr": error_output if error_output else None,
        "return_code": proc.returncode,
        "success": proc.returncode == 0,
    }
