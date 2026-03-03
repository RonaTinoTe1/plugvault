#!/usr/bin/env python3
"""
GitHub Scanner for PlugVault
Scans GitHub for Claude plugins using search queries and awesome-lists.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SOURCES_FILE = os.path.join(DATA_DIR, "sources.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "new-plugins.json")
MIN_STARS = 2
MAX_COMMIT_AGE_DAYS = 90

# Rate limiting
GITHUB_RATE_LIMIT_DELAY = 2  # seconds between requests

# Repo name patterns that indicate non-production repos
EXCLUDED_NAME_PATTERNS: frozenset[str] = frozenset([
    "test", "demo", "hello-world", "example", "template",
    "boilerplate", "tutorial", "sample", "playground",
])


class GitHubScanner:
    def __init__(self, token: str | None = None):
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"token {token}"})
        self.session.headers.update(
            {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "PlugVault-Scanner/1.0",
            }
        )
        self.found_plugins: dict[str, dict[str, Any]] = {}
        self.last_request_time = 0

    def _make_request(self, url: str, params: dict | None = None) -> dict | None:
        """Make a rate-limited request to GitHub API with retry logic."""
        # Simple rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < GITHUB_RATE_LIMIT_DELAY:
            time.sleep(GITHUB_RATE_LIMIT_DELAY - elapsed)

        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=30)
                self.last_request_time = time.time()

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 403:
                    # Check if this is a real rate limit via headers
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    reset_time = response.headers.get("X-RateLimit-Reset")
                    if remaining is not None and int(remaining) == 0 and reset_time:
                        wait_seconds = max(int(reset_time) - int(time.time()), 1)
                        logger.warning("Rate limited, waiting %ds (attempt %d/3)", wait_seconds, attempt + 1)
                        time.sleep(min(wait_seconds, 120))
                    else:
                        backoff = 2 ** attempt
                        logger.warning("403 response (attempt %d/3), retrying in %ds", attempt + 1, backoff)
                        time.sleep(backoff)
                    continue

                logger.warning("Error %d: %s", response.status_code, url)
                return None

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                backoff = 2 ** attempt
                logger.warning("Network error (attempt %d/3): %s, retrying in %ds", attempt + 1, e, backoff)
                time.sleep(backoff)
            except Exception as e:
                logger.error("Request error: %s", e)
                return None

        logger.error("Failed request after 3 attempts: %s", url)
        return None

    def search_repos(self, query: str) -> list[dict]:
        """Search GitHub repositories with a query."""
        logger.info("  Searching: %s", query)
        results = []
        page = 1
        max_pages = 10  # Limit to 1000 results

        while page <= max_pages:
            data = self._make_request(
                "https://api.github.com/search/repositories",
                params={"q": query, "per_page": 100, "page": page},
            )

            if not data or "items" not in data:
                break

            results.extend(data["items"])

            if len(data["items"]) < 100:
                break

            page += 1

        logger.info("    Found %d repositories", len(results))
        return results

    def get_repo_details(self, owner: str, repo: str) -> dict | None:
        """Get detailed repository information."""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        return self._make_request(url)

    def get_repo_contents(self, owner: str, repo: str) -> list[dict] | None:
        """Get repository root contents."""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents"
        return self._make_request(url)

    def detect_plugin_type(self, owner: str, repo: str, contents: list | None) -> str:
        """Detect the type of plugin based on repository structure."""
        if not contents:
            return "unknown"

        files = {item.get("name", "").lower() for item in contents if isinstance(item, dict)}
        dirs = {item.get("name", "").lower() for item in contents if isinstance(item, dict) and item.get("type") == "dir"}

        has_plugin_json = "plugin.json" in files
        has_claude_plugin_dir = ".claude-plugin" in dirs
        has_mcp = any("mcp" in f for f in files) or any("mcp" in d for d in dirs)
        has_hooks = "hooks" in dirs or any("hook" in f for f in files)
        has_skills = "skills" in dirs or any("skill" in f for f in files)

        types = []
        if has_plugin_json or has_claude_plugin_dir or has_skills:
            types.append("plugin")
        if has_mcp:
            types.append("mcp")
        if has_hooks:
            types.append("hooks")

        if len(types) > 1:
            return "mixed"
        elif types:
            return types[0]
        return "unknown"

    def is_valid_plugin(self, repo_data: dict) -> bool:
        """Check if repository meets plugin criteria."""
        # Check stars
        stars = repo_data.get("stargazers_count", 0)
        if stars <= MIN_STARS:
            return False

        # Check last commit date
        pushed_at = repo_data.get("pushed_at")
        if pushed_at:
            last_push = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_COMMIT_AGE_DAYS)
            if last_push < cutoff:
                return False

        # Exclude test/demo/template repos by name
        name = repo_data.get("name", "").lower()
        if any(pattern in name for pattern in EXCLUDED_NAME_PATTERNS):
            logger.debug("      Skipped: name matches exclusion pattern (%s)", name)
            return False

        return True

    def has_plugin_files(self, owner: str, repo: str) -> bool:
        """Check if repo has plugin-related files and meets minimum file count."""
        contents = self.get_repo_contents(owner, repo)
        if not contents:
            return False

        # Exclude repos with fewer than 3 root-level entries
        if len(contents) < 3:
            logger.debug("      Skipped: fewer than 3 files in root")
            return False

        files = {item.get("name", "").lower() for item in contents if isinstance(item, dict)}
        dirs = {item.get("name", "").lower() for item in contents if isinstance(item, dict) and item.get("type") == "dir"}

        # Check for plugin indicators
        if "plugin.json" in files:
            return True
        if ".claude-plugin" in dirs:
            return True
        if any("mcp" in f for f in files):
            return True
        if any("mcp" in d for d in dirs):
            return True

        return False

    def search_code(self, query: str) -> list[dict]:
        """Search GitHub code and return unique repository data dicts."""
        logger.info("  Code search: %s", query)
        data = self._make_request(
            "https://api.github.com/search/code",
            params={"q": query, "per_page": 30},
        )
        if not data or "items" not in data:
            return []

        seen: set[str] = set()
        repos: list[dict] = []
        for item in data["items"]:
            repo = item.get("repository", {})
            url = repo.get("html_url", "")
            if url and url not in seen:
                seen.add(url)
                repos.append(repo)

        logger.info("    Found %d unique repositories", len(repos))
        return repos

    def process_repo(self, repo_data: dict, discovered_via: str = "github-search") -> dict | None:
        """Process a repository and extract plugin information."""
        full_name = repo_data.get("full_name", "")
        owner = repo_data.get("owner", {}).get("login", "")
        repo = repo_data.get("name", "")

        logger.info("    Processing: %s", full_name)

        # Check if already found
        github_url = repo_data.get("html_url", "")
        if github_url in self.found_plugins:
            return None

        # Validate
        if not self.is_valid_plugin(repo_data):
            logger.debug("      Skipped: Does not meet criteria")
            return None

        # Check for plugin files (also enforces minimum file count)
        if not self.has_plugin_files(owner, repo):
            logger.debug("      Skipped: No plugin files found")
            return None

        # Get more details
        contents = self.get_repo_contents(owner, repo)
        plugin_type = self.detect_plugin_type(owner, repo, contents)

        # Build plugin entry
        plugin = {
            "name": repo_data.get("name", ""),
            "github_url": github_url,
            "github_owner": owner,
            "github_repo": repo,
            "description": repo_data.get("description", ""),
            "stars": repo_data.get("stargazers_count", 0),
            "forks": repo_data.get("forks_count", 0),
            "open_issues": repo_data.get("open_issues_count", 0),
            "topics": repo_data.get("topics", []),
            "last_commit": repo_data.get("pushed_at", ""),
            "plugin_type": plugin_type,
            "language": repo_data.get("language", ""),
            "license": repo_data.get("license", {}).get("spdx_id", "") if repo_data.get("license") else "",
            "discovered_via": discovered_via,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        }

        self.found_plugins[github_url] = plugin
        logger.info("      Added: %s plugin with %d stars", plugin_type, plugin["stars"])
        return plugin

    def scan_single_url(self, github_url: str) -> dict | None:
        """Scan a single GitHub repo by URL, bypassing star/age/file filters.

        Used for manual submissions where the user explicitly provides the URL.
        """
        github_url = github_url.rstrip("/")
        if github_url.endswith(".git"):
            github_url = github_url[:-4]

        parsed = urlparse(github_url)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) < 2:
            logger.error("Invalid GitHub URL: %s", github_url)
            return None

        owner, repo = path_parts[0], path_parts[1]
        logger.info("Fetching repo: %s/%s", owner, repo)

        repo_data = self.get_repo_details(owner, repo)
        if not repo_data:
            logger.error("Could not fetch repo details for %s/%s", owner, repo)
            return None

        html_url = repo_data.get("html_url", github_url)
        if html_url in self.found_plugins:
            logger.info("Already scanned: %s", html_url)
            return self.found_plugins[html_url]

        contents = self.get_repo_contents(owner, repo)
        plugin_type = self.detect_plugin_type(owner, repo, contents)

        plugin = {
            "name": repo_data.get("name", repo),
            "github_url": html_url,
            "github_owner": owner,
            "github_repo": repo,
            "description": repo_data.get("description", ""),
            "stars": repo_data.get("stargazers_count", 0),
            "forks": repo_data.get("forks_count", 0),
            "open_issues": repo_data.get("open_issues_count", 0),
            "topics": repo_data.get("topics", []),
            "last_commit": repo_data.get("pushed_at", ""),
            "plugin_type": plugin_type,
            "language": repo_data.get("language", ""),
            "license": (
                repo_data.get("license", {}).get("spdx_id", "")
                if repo_data.get("license")
                else ""
            ),
            "discovered_via": "submission",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        }

        self.found_plugins[html_url] = plugin
        logger.info("Added: %s (%s plugin, %d stars)", html_url, plugin_type, plugin["stars"])
        return plugin

    def extract_github_urls_from_readme(self, readme_content: str) -> set[str]:
        """Extract GitHub URLs from README content."""
        urls = set()

        # Match github.com URLs
        pattern = r'https?://github\.com/([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)'
        matches = re.findall(pattern, readme_content)

        for match in matches:
            # Clean up the URL (remove trailing punctuation and anchors)
            clean_path = match.rstrip('/').rstrip('.').rstrip(',')
            if clean_path and '/' in clean_path:
                urls.add(f"https://github.com/{clean_path}")

        return urls

    def scan_awesome_lists(self, awesome_lists: list[dict]) -> None:
        """Scan awesome-lists for plugin URLs."""
        logger.info("Scanning awesome-lists...")

        for aw_list in awesome_lists:
            raw_url = aw_list.get("raw_readme", "")
            if not raw_url:
                continue

            logger.info("  Fetching: %s", aw_list.get('name', raw_url))

            try:
                response = self.session.get(raw_url, timeout=30)
                if response.status_code == 200:
                    urls = self.extract_github_urls_from_readme(response.text)
                    logger.info("    Found %d GitHub URLs", len(urls))

                    for url in urls:
                        if url in self.found_plugins:
                            continue

                        # Parse owner/repo from URL
                        parsed = urlparse(url)
                        path_parts = parsed.path.strip('/').split('/')
                        if len(path_parts) >= 2:
                            owner, repo = path_parts[0], path_parts[1]

                            # Get repo details
                            repo_data = self.get_repo_details(owner, repo)
                            if repo_data:
                                self.process_repo(repo_data, discovered_via="awesome-list")

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.warning("Network error fetching awesome-list: %s", e)
            except Exception as e:
                logger.error("Error scanning awesome-list: %s", e)

    def run(self, sources: dict) -> dict:
        """Run the scanner with the given sources."""
        # Search using configured queries
        queries = sources.get("github_search_queries", [])
        logger.info("Searching GitHub with repository queries...")
        for query in queries:
            repos = self.search_repos(query)
            for repo in repos:
                self.process_repo(repo, discovered_via="github-search")

        # Additional topic queries (hardcoded discovery vectors)
        extra_topic_queries = [
            "topic:claude-code-skills",
            "topic:mcp-server",
        ]
        logger.info("Searching additional topic queries...")
        for query in extra_topic_queries:
            repos = self.search_repos(query)
            for repo in repos:
                self.process_repo(repo, discovered_via="github-search")

        # Code search queries (GitHub code search API)
        code_queries = [
            "path:.claude/agents",
            "filename:CLAUDE.md claude plugin",
        ]
        logger.info("Running code search queries...")
        for query in code_queries:
            repos = self.search_code(query)
            for repo in repos:
                self.process_repo(repo, discovered_via="code-search")

        # Scan awesome-lists
        awesome_lists = sources.get("awesome_lists", [])
        self.scan_awesome_lists(awesome_lists)

        # Build output
        output = {
            "scan_date": datetime.now(timezone.utc).isoformat(),
            "plugins_found": len(self.found_plugins),
            "plugins": list(self.found_plugins.values()),
        }

        return output


def main():
    parser = argparse.ArgumentParser(description="PlugVault GitHub Scanner")
    parser.add_argument(
        "--single-url",
        metavar="URL",
        help="Scan a single GitHub repository URL instead of running the full scan",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("PlugVault GitHub Scanner")
    logger.info("=" * 60)

    # Get GitHub token
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        logger.warning("GITHUB_TOKEN not set. Rate limits will be restrictive.")

    scanner = GitHubScanner(token)

    if args.single_url:
        # Single-URL mode: scan one repo, bypass star/age/file filters
        logger.info("Single-URL mode: %s", args.single_url)
        plugin = scanner.scan_single_url(args.single_url)
        if not plugin:
            logger.error("Failed to scan URL: %s", args.single_url)
            sys.exit(1)
        results = {
            "scan_date": datetime.now(timezone.utc).isoformat(),
            "plugins_found": 1,
            "plugins": [plugin],
        }
    else:
        # Full scan mode — requires sources.json
        try:
            with open(SOURCES_FILE, "r") as f:
                sources = json.load(f)
        except FileNotFoundError:
            logger.error("Sources file not found: %s", SOURCES_FILE)
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in sources file: %s", e)
            sys.exit(1)
        results = scanner.run(sources)

    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)

    # Write output
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    logger.info("=" * 60)
    logger.info("Scan complete!")
    logger.info("  Plugins found: %d", results["plugins_found"])
    logger.info("  Output: %s", OUTPUT_FILE)
    logger.info("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    main()
