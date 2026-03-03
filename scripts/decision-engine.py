#!/usr/bin/env python3
"""
Decision Engine for PlugVault
Decides a plugin submission outcome: AUTO_MERGE, WAIT, or REJECT.

Usage:
  python scripts/decision-engine.py \
    --security-report path/to/report.json \
    --quality-score 75 \
    [--plugin-file path/to/plugin.json]

Exit codes:
  0 = AUTO_MERGE
  1 = WAIT
  2 = REJECT
  3 = Error (bad input)
"""

import argparse
import json
import sys


def load_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(3)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(3)


def decide(security_score: str, quality_score: int) -> tuple[str, str]:
    """Return (decision, reason) based on security and quality scores."""
    s = security_score.upper().strip()

    if s == "DANGER":
        return (
            "REJECT",
            "Security score is DANGER — critical security issues detected",
        )

    if s == "SAFE" and quality_score >= 60:
        return (
            "AUTO_MERGE",
            f"Security SAFE and quality score {quality_score}/100 meets threshold (>=60)",
        )

    if s == "CAUTION":
        return (
            "WAIT",
            "Security score is CAUTION — manual human review required",
        )

    # SAFE but quality below threshold
    return (
        "WAIT",
        f"Security SAFE but quality score {quality_score}/100 is below threshold (<60)",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="PlugVault Decision Engine")
    parser.add_argument(
        "--plugin-file",
        default=None,
        help="Path to plugin JSON file (optional)",
    )
    parser.add_argument(
        "--security-report",
        required=True,
        help="Path to security report JSON",
    )
    parser.add_argument(
        "--quality-score",
        required=True,
        type=int,
        help="Quality score (0–100)",
    )
    args = parser.parse_args()

    report = load_json(args.security_report)
    security_score = report.get(
        "score", report.get("security_score", "UNKNOWN")
    ).upper()

    if security_score not in ("SAFE", "CAUTION", "DANGER"):
        print(
            f"Warning: Unknown security score '{security_score}', treating as CAUTION",
            file=sys.stderr,
        )
        security_score = "CAUTION"

    # Base plugin info from security report (overridable by plugin file)
    plugin_name = report.get("plugin", report.get("plugin_name", "unknown"))
    plugin_url = report.get("github_url", "")

    if args.plugin_file:
        plugin_data = load_json(args.plugin_file)
        plugin_name = plugin_data.get("name", plugin_name)
        plugin_url = plugin_data.get(
            "github_url", plugin_data.get("github", plugin_url)
        )

    decision, reason = decide(security_score, args.quality_score)

    output = {
        "decision": decision,
        "reason": reason,
        "security_score": security_score,
        "quality_score": args.quality_score,
        "plugin_name": plugin_name,
        "plugin_url": plugin_url,
        "issues_count": len(report.get("issues", [])),
    }

    print(json.dumps(output, indent=2))

    exit_codes = {"AUTO_MERGE": 0, "WAIT": 1, "REJECT": 2}
    sys.exit(exit_codes[decision])


if __name__ == "__main__":
    main()
