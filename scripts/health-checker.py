#!/usr/bin/env python3
"""
PlugVault Health Checker
Monitors plugin repository health and updates history metrics.

Usage:
  python scripts/health-checker.py --catalog catalog.json --output data/health-report.json

Environment variables:
  GITHUB_TOKEN  - GitHub API token for higher rate limits (recommended)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "plugin-history.json")
HISTORY_WEEKS = 12  # Keep 12 weeks of history

# Status thresholds (days since last commit)
THRESHOLD_ACTIVE = 90
THRESHOLD_ARCHIVED_DAYS = 180

GITHUB_DELAY = 1.2  # seconds between GitHub API calls


class GitHubClient:
    """Minimal GitHub API client with rate limit handling."""

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.session = requests.Session()
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PlugVault-HealthChecker/1.0",
        }
        if token:
            headers["Authorization"] = f"token {token}"
        self.session.headers.update(headers)
        self._last_request = 0.0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < GITHUB_DELAY:
            time.sleep(GITHUB_DELAY - elapsed)

    def _get(self, url: str) -> Optional[dict]:
        self._rate_limit()
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=15)
                self._last_request = time.time()

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 403:
                    remaining = resp.headers.get("X-RateLimit-Remaining", "1")
                    reset_ts = resp.headers.get("X-RateLimit-Reset")
                    if remaining == "0" and reset_ts:
                        wait = max(int(reset_ts) - int(time.time()), 1)
                        logger.warning("Rate limited — waiting %ds", wait)
                        time.sleep(min(wait, 120))
                    else:
                        time.sleep(2 ** attempt)
                elif resp.status_code == 404:
                    return None
                else:
                    logger.warning("HTTP %d for %s (attempt %d/3)", resp.status_code, url, attempt + 1)
                    time.sleep(2 ** attempt)
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning("Network error (attempt %d/3): %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
            except Exception as exc:
                logger.error("Unexpected error for %s: %s", url, exc)
                return None
        return None

    def get_repo(self, owner: str, repo: str) -> Optional[dict]:
        return self._get(f"https://api.github.com/repos/{owner}/{repo}")

    def get_commits(self, owner: str, repo: str) -> Optional[list]:
        return self._get(f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1")


def parse_github_url(url: str) -> Optional[tuple[str, str]]:
    """Extract (owner, repo) from a GitHub URL."""
    if not url:
        return None
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2 and "github.com" in url:
        return parts[-2], parts[-1]
    return None


def check_url_accessible(url: str) -> tuple[bool, int]:
    """Check if a URL responds (HEAD request). Returns (accessible, status_code)."""
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True,
                             headers={"User-Agent": "PlugVault-HealthChecker/1.0"})
        return resp.status_code not in (404, 410), resp.status_code
    except Exception:
        return False, 0


def days_since(date_str: str) -> Optional[int]:
    """Return number of days since a date string (ISO 8601)."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return None


def load_json(path: str, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def compute_stars_trend(slug: str, current_stars: int, history: dict) -> str:
    """
    Compare current stars to 2-week-old entry.
    Returns 'declining', 'growing', or 'stable'.
    """
    entries = history.get(slug, [])
    if len(entries) < 2:
        return "stable"

    # Find entry closest to 14 days ago
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    old_entry = None
    for e in reversed(entries):
        if e["date"] <= cutoff:
            old_entry = e
            break

    if old_entry is None:
        # Use oldest available
        old_entry = entries[0]

    old_stars = old_entry.get("stars", 0)
    if current_stars < old_stars:
        return "declining"
    if current_stars > old_stars:
        return "growing"
    return "stable"


def update_history(slug: str, metrics: dict, history: dict) -> None:
    """Append today's metrics to history, keeping last HISTORY_WEEKS weeks."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = {
        "date": today,
        "stars": metrics.get("stars", 0),
        "forks": metrics.get("forks", 0),
        "open_issues": metrics.get("open_issues", 0),
    }

    if slug not in history:
        history[slug] = []

    # Remove duplicate entry for today if exists
    history[slug] = [e for e in history[slug] if e["date"] != today]
    history[slug].append(entry)

    # Keep only last 12 weeks (84 days) of entries
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=HISTORY_WEEKS)).strftime("%Y-%m-%d")
    history[slug] = [e for e in history[slug] if e["date"] >= cutoff]


def check_plugin(plugin: dict, client: GitHubClient, history: dict, has_token: bool) -> dict:
    """Check the health of a single plugin."""
    slug = plugin.get("slug") or plugin.get("name", "unknown").lower()
    github_url = plugin.get("github_url", "")

    result = {
        "status": "unknown",
        "days_since_commit": None,
        "stars_trend": "stable",
        "github_accessible": False,
        "github_archived": False,
    }

    # 1. Check URL accessibility
    if github_url:
        accessible, status_code = check_url_accessible(github_url)
        result["github_accessible"] = accessible
        if not accessible:
            logger.info("  [%s] URL not accessible (HTTP %d) → dead", slug, status_code)
            result["status"] = "dead"
            return result
    else:
        logger.info("  [%s] No github_url → skipping checks", slug)
        return result

    # 2. GitHub API checks (if token available or graceful fallback)
    parsed = parse_github_url(github_url)
    if not parsed:
        logger.warning("  [%s] Could not parse GitHub URL: %s", slug, github_url)
        result["status"] = "active"
        return result

    owner, repo = parsed

    if has_token:
        repo_info = client.get_repo(owner, repo)
    else:
        logger.info("  [%s] No GITHUB_TOKEN — skipping API checks", slug)
        result["status"] = "active"
        return result

    if repo_info is None:
        logger.info("  [%s] GitHub API returned None (private or 404) → dead", slug)
        result["status"] = "dead"
        return result

    # 3. Check archived flag
    github_archived = repo_info.get("archived", False)
    result["github_archived"] = github_archived

    # 4. Extract metrics
    stars = repo_info.get("stargazers_count", 0)
    forks = repo_info.get("forks_count", 0)
    open_issues = repo_info.get("open_issues_count", 0)
    pushed_at = repo_info.get("pushed_at", "")

    # 5. Update history
    update_history(slug, {"stars": stars, "forks": forks, "open_issues": open_issues}, history)

    # 6. Compute stars trend
    result["stars_trend"] = compute_stars_trend(slug, stars, history)

    # 7. Days since last commit
    d = days_since(pushed_at)
    result["days_since_commit"] = d

    # 8. Determine status
    if github_archived:
        result["status"] = "archived"
    elif d is None:
        result["status"] = "active"
    elif d > THRESHOLD_ARCHIVED_DAYS:
        result["status"] = "archived"
    elif d > THRESHOLD_ACTIVE:
        result["status"] = "maintenance"
    else:
        result["status"] = "active"

    logger.info(
        "  [%s] status=%s days_since_commit=%s stars_trend=%s archived=%s",
        slug, result["status"], d, result["stars_trend"], github_archived,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="PlugVault Health Checker")
    parser.add_argument("--catalog", default="catalog.json", help="Path to catalog.json")
    parser.add_argument("--output", default="data/health-report.json", help="Output health report path")
    args = parser.parse_args()

    catalog_path = os.path.join(BASE_DIR, args.catalog) if not os.path.isabs(args.catalog) else args.catalog
    output_path = os.path.join(BASE_DIR, args.output) if not os.path.isabs(args.output) else args.output

    logger.info("=" * 60)
    logger.info("PlugVault Health Checker")
    logger.info("Catalog: %s", catalog_path)
    logger.info("Output:  %s", output_path)
    logger.info("=" * 60)

    # Load catalog
    catalog = load_json(catalog_path, {"plugins": []})
    plugins = catalog.get("plugins", [])
    logger.info("Loaded %d plugins from catalog", len(plugins))

    if not plugins:
        logger.warning("No plugins found in catalog. Exiting.")
        sys.exit(0)

    # GitHub token
    token = os.environ.get("GITHUB_TOKEN")
    has_token = bool(token)
    if not has_token:
        logger.warning("GITHUB_TOKEN not set — API checks will be skipped (graceful degradation)")

    client = GitHubClient(token)

    # Load existing history
    history = load_json(HISTORY_FILE, {})

    # Check each plugin
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_plugins = {}
    summary = {"total": 0, "active": 0, "archived": 0, "dead": 0, "maintenance": 0, "unknown": 0}

    for plugin in plugins:
        slug = plugin.get("slug") or plugin.get("name", "unknown").lower()
        logger.info("Checking plugin: %s", slug)
        result = check_plugin(plugin, client, history, has_token)
        report_plugins[slug] = result

        summary["total"] += 1
        status = result["status"]
        summary[status] = summary.get(status, 0) + 1

    # Save updated history
    save_json(HISTORY_FILE, history)
    logger.info("Updated history: %s", HISTORY_FILE)

    # Build and save health report
    report = {
        "check_date": today,
        "plugins": report_plugins,
        "summary": summary,
    }
    save_json(output_path, report)
    logger.info("Health report saved: %s", output_path)

    logger.info("=" * 60)
    logger.info("Health check complete!")
    for k, v in summary.items():
        logger.info("  %s: %d", k, v)
    logger.info("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    main()
