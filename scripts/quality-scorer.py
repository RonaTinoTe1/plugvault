#!/usr/bin/env python3
"""
PlugVault Quality Scorer
CLI: python scripts/quality-scorer.py --github-url https://github.com/user/repo --output score.json

Scores a plugin 0-100 using only local analysis + GitHub API (no AI required).
Deterministic and reproducible.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Repo cloning
# ---------------------------------------------------------------------------

def clone_repo(github_url: str) -> tuple:
    """Clone repo (depth=1) to a tmpdir. Returns (tmpdir, error_str)."""
    tmpdir = tempfile.mkdtemp(prefix="plugvault-score-")
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", github_url, tmpdir],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, f"Clone failed: {result.stderr.strip()}"
        return tmpdir, None
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, "Clone timed out (>60s)"
    except FileNotFoundError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, "git not found on PATH"
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, str(e)


# ---------------------------------------------------------------------------
# README Quality  (max 30 pts)
# ---------------------------------------------------------------------------

def score_readme(repo_path: str) -> tuple:
    """Score README quality. Returns (score, details_dict)."""
    details = {}
    score = 0
    p = Path(repo_path)

    readme_content = None
    for candidate in ("README.md", "README.MD", "readme.md", "README.txt", "README"):
        rp = p / candidate
        if rp.exists():
            try:
                readme_content = rp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
            break

    if readme_content is None:
        details["exists"] = False
        details["length"] = 0
        return 0, details

    score += 5
    details["exists"] = True
    details["length"] = len(readme_content)
    lower = readme_content.lower()

    # > 500 chars
    if len(readme_content) > 500:
        score += 5
        details["gt500"] = True
    else:
        details["gt500"] = False

    # > 2000 chars (bonus)
    if len(readme_content) > 2000:
        score += 5
        details["gt2000"] = True
    else:
        details["gt2000"] = False

    # Code blocks
    if "```" in readme_content:
        score += 5
        details["has_code_blocks"] = True
    else:
        details["has_code_blocks"] = False

    # Installation section
    if re.search(r"(install|setup|usage)", lower):
        score += 5
        details["has_install_section"] = True
    else:
        details["has_install_section"] = False

    # Example / usage section
    if re.search(r"(example|usage)", lower):
        score += 5
        details["has_example_section"] = True
    else:
        details["has_example_section"] = False

    return score, details


# ---------------------------------------------------------------------------
# Maintenance Activity  (max 25 pts)
# ---------------------------------------------------------------------------

def score_maintenance(repo_path: str) -> tuple:
    """Score based on last git commit date. Returns (score, details_dict)."""
    details = {}
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0 or not result.stdout.strip():
            details["last_commit"] = None
            details["days_since_commit"] = None
            return 0, details

        raw = result.stdout.strip()
        last_commit = datetime.fromisoformat(raw)
        if last_commit.tzinfo is None:
            last_commit = last_commit.replace(tzinfo=timezone.utc)

        days = (datetime.now(timezone.utc) - last_commit).days
        details["last_commit"] = last_commit.isoformat()
        details["days_since_commit"] = days

        if days < 7:
            pts = 25
        elif days < 30:
            pts = 20
        elif days < 60:
            pts = 12
        elif days < 90:
            pts = 5
        else:
            pts = 0

        return pts, details

    except Exception as e:
        details["error"] = str(e)
        return 0, details


# ---------------------------------------------------------------------------
# GitHub Health  (max 20 pts)
# ---------------------------------------------------------------------------

def score_github_health(github_url: str) -> tuple:
    """Score stars + issue ratio via GitHub API. Returns (score, details_dict)."""
    details = {"stars": 0, "open_issues": 0, "forks": 0}
    parts = github_url.rstrip("/").split("/")
    if len(parts) < 2:
        details["error"] = "Cannot parse owner/repo from URL"
        return 0, details

    owner, repo = parts[-2], parts[-1]
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "User-Agent": "PlugVault-Scorer/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        stars = data.get("stargazers_count", 0)
        open_issues = data.get("open_issues_count", 0)
        details["stars"] = stars
        details["open_issues"] = open_issues
        details["forks"] = data.get("forks_count", 0)

        # Stars scoring
        if stars > 100:
            pts = 20
        elif stars > 50:
            pts = 15
        elif stars > 10:
            pts = 10
        elif stars > 2:
            pts = 5
        else:
            pts = 0

        # Low issue ratio bonus (capped at 20 total)
        if stars > 0 and open_issues < (stars * 0.1):
            pts = min(pts + 5, 20)
            details["low_issue_ratio"] = True
        else:
            details["low_issue_ratio"] = False

        return pts, details

    except urllib.error.HTTPError as e:
        details["error"] = f"HTTP {e.code}"
        return 0, details
    except Exception as e:
        details["error"] = str(e)
        return 0, details


# ---------------------------------------------------------------------------
# Documentation  (max 15 pts)
# ---------------------------------------------------------------------------

def score_documentation(repo_path: str) -> tuple:
    """Score presence of CHANGELOG, LICENSE, and examples. Returns (score, details_dict)."""
    details = {}
    score = 0
    p = Path(repo_path)

    # CHANGELOG
    has_changelog = any(
        (p / n).exists()
        for n in ("CHANGELOG.md", "CHANGELOG", "CHANGELOG.txt", "changelog.md", "CHANGES.md")
    )
    if has_changelog:
        score += 5
        details["has_changelog"] = True
    else:
        details["has_changelog"] = False

    # LICENSE
    has_license = any(
        (p / n).exists()
        for n in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md")
    )
    if has_license:
        score += 5
        details["has_license"] = True
    else:
        details["has_license"] = False

    # Examples directory or "example" in README
    has_examples = (p / "examples").is_dir() or (p / "example").is_dir()
    if not has_examples:
        for name in ("README.md", "README.MD", "readme.md"):
            rp = p / name
            if rp.exists():
                try:
                    if "example" in rp.read_text(encoding="utf-8", errors="replace").lower():
                        has_examples = True
                except Exception:
                    pass
                break

    if has_examples:
        score += 5
        details["has_examples"] = True
    else:
        details["has_examples"] = False

    return score, details


# ---------------------------------------------------------------------------
# Plugin Structure  (max 10 pts)
# ---------------------------------------------------------------------------

def score_structure(repo_path: str) -> tuple:
    """Score Claude plugin structure. Returns (score, details_dict)."""
    details = {}
    score = 0
    p = Path(repo_path)

    # plugin.json: +4
    has_plugin_json = (p / "plugin.json").exists() or (p / ".claude-plugin" / "plugin.json").exists()
    if has_plugin_json:
        score += 4
        details["has_plugin_json"] = True
    else:
        details["has_plugin_json"] = False

    # .claude/ directory: +3
    if (p / ".claude").is_dir():
        score += 3
        details["has_claude_dir"] = True
    else:
        details["has_claude_dir"] = False

    # skills/ directory: +2
    if (p / "skills").is_dir():
        score += 2
        details["has_skills_dir"] = True
    else:
        details["has_skills_dir"] = False

    # hooks/ directory: +1
    if (p / "hooks").is_dir():
        score += 1
        details["has_hooks_dir"] = True
    else:
        details["has_hooks_dir"] = False

    return score, details


# ---------------------------------------------------------------------------
# Grade & recommendation
# ---------------------------------------------------------------------------

def compute_grade(score: int) -> str:
    if score >= 85:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 55:
        return "C"
    elif score >= 40:
        return "D"
    return "F"


def compute_recommendation(score: int, grade: str) -> str:
    messages = {
        "A": "Excellent plugin — well maintained, documented, and structured",
        "B": "Good plugin, well maintained",
        "C": "Fair plugin, could benefit from more documentation",
        "D": "Below average — significant improvements recommended",
        "F": "Poor quality — major improvements required before listing",
    }
    return messages.get(grade, "Quality assessment unavailable")


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------

def score_plugin(github_url: str) -> dict:
    """Score a plugin end-to-end. Always returns a complete result dict."""
    if not github_url.startswith("https://github.com/"):
        return _fail_result(github_url, "URL must start with https://github.com/")

    tmpdir, clone_error = clone_repo(github_url)
    if clone_error:
        return _fail_result(github_url, clone_error)

    try:
        readme_pts, readme_det = score_readme(tmpdir)
        maint_pts, maint_det = score_maintenance(tmpdir)
        gh_pts, gh_det = score_github_health(github_url)
        docs_pts, docs_det = score_documentation(tmpdir)
        struct_pts, struct_det = score_structure(tmpdir)

        total = readme_pts + maint_pts + gh_pts + docs_pts + struct_pts
        grade = compute_grade(total)

        return {
            "score": total,
            "grade": grade,
            "breakdown": {
                "readme": readme_pts,
                "maintenance": maint_pts,
                "github_health": gh_pts,
                "documentation": docs_pts,
                "structure": struct_pts,
            },
            "recommendation": compute_recommendation(total, grade),
            "details": {
                "readme": readme_det,
                "maintenance": maint_det,
                "github_health": gh_det,
                "documentation": docs_det,
                "structure": struct_det,
            },
            "github_url": github_url,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _fail_result(github_url: str, reason: str) -> dict:
    return {
        "score": 0,
        "grade": "N/A",
        "breakdown": {
            "readme": 0,
            "maintenance": 0,
            "github_health": 0,
            "documentation": 0,
            "structure": 0,
        },
        "recommendation": reason,
        "details": {"error": reason},
        "github_url": github_url,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PlugVault Quality Scorer — score a plugin repo 0-100"
    )
    parser.add_argument("--github-url", required=True, help="GitHub repository URL")
    parser.add_argument("--output", help="Output JSON file (default: stdout)")
    parser.add_argument("--slug", help="Plugin slug (used in output filename if --output is a directory)")
    args = parser.parse_args()

    print(f"Scoring: {args.github_url}", file=sys.stderr)
    result = score_plugin(args.github_url)

    # Print summary to stderr
    bd = result["breakdown"]
    print(f"Score: {result['score']}/100  Grade: {result['grade']}", file=sys.stderr)
    print(f"  README       {bd['readme']:3d}/30", file=sys.stderr)
    print(f"  Maintenance  {bd['maintenance']:3d}/25", file=sys.stderr)
    print(f"  GitHub Health{bd['github_health']:3d}/20", file=sys.stderr)
    print(f"  Documentation{bd['documentation']:3d}/15", file=sys.stderr)
    print(f"  Structure    {bd['structure']:3d}/10", file=sys.stderr)
    print(f"Recommendation: {result['recommendation']}", file=sys.stderr)

    json_output = json.dumps(result, indent=2)

    if args.output:
        output_path = Path(args.output)
        # If output is a directory, auto-name the file
        if output_path.is_dir():
            slug = args.slug or re.sub(r"[^a-z0-9\-]", "-", args.github_url.rstrip("/").split("/")[-1].lower())
            output_path = output_path / f"{slug}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_output, encoding="utf-8")
        print(f"Saved: {output_path}", file=sys.stderr)
    else:
        print(json_output)


if __name__ == "__main__":
    main()
