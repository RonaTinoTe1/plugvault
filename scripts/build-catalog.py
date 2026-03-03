#!/usr/bin/env python3
"""
Catalog Builder for PlugVault
Builds the final catalog.json from scanned plugins and security reports.

Environment variables:
  GITHUB_TOKEN       - GitHub API token for higher rate limits
  ENRICH_GITHUB=true - Enable live GitHub enrichment (fetches stars, forks, etc.)
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
NEW_PLUGINS_FILE = os.path.join(DATA_DIR, "new-plugins.json")
CATALOG_FILE = os.path.join(BASE_DIR, "catalog.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "blacklist.json")
CATEGORIES_FILE = os.path.join(DATA_DIR, "categories.json")
SECURITY_REPORTS_DIR = os.path.join(DATA_DIR, "security-reports")
QUALITY_SCORES_DIR = os.path.join(DATA_DIR, "quality-scores")
HEALTH_REPORT_FILE = os.path.join(DATA_DIR, "health-report.json")
ARCHIVED_PLUGINS_FILE = os.path.join(DATA_DIR, "archived-plugins.json")

# Rate limiting for GitHub API
GITHUB_DELAY = 1  # seconds between requests

# GitHub enrichment flag (set ENRICH_GITHUB=true to enable)
ENRICH_GITHUB = os.environ.get("ENRICH_GITHUB", "").lower() == "true"


def slugify(name: str) -> str:
    """Convert name to URL-safe slug."""
    slug = re.sub(r'[^a-zA-Z0-9\-]', '-', name.lower())
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def load_json_file(path: str, default: Any = None) -> Any:
    """Load JSON file with default fallback."""
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return default


def save_json_file(path: str, data: Any) -> None:
    """Save data to JSON file."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


class GitHubEnricher:
    """Enrich plugin data with fresh GitHub information."""

    def __init__(self, token: str | None = None):
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"token {token}"})
        self.session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PlugVault-Builder/1.0",
        })
        self.last_request = 0

    def _rate_limit(self):
        """Simple rate limiting."""
        elapsed = time.time() - self.last_request
        if elapsed < GITHUB_DELAY:
            time.sleep(GITHUB_DELAY - elapsed)

    def get_repo_info(self, owner: str, repo: str) -> dict | None:
        """Get repository information from GitHub API with retry logic."""
        self._rate_limit()
        url = f"https://api.github.com/repos/{owner}/{repo}"

        for attempt in range(3):
            try:
                response = self.session.get(url, timeout=30)
                self.last_request = time.time()

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 403:
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
                else:
                    logger.warning("Unexpected status %d for %s/%s", response.status_code, owner, repo)
                    return None
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                backoff = 2 ** attempt
                logger.warning("Network error (attempt %d/3): %s, retrying in %ds", attempt + 1, e, backoff)
                time.sleep(backoff)
            except Exception as e:
                logger.error("Error fetching repo info for %s/%s: %s", owner, repo, e)
                return None

        logger.error("Failed to fetch repo info for %s/%s after 3 attempts", owner, repo)
        return None


class Categorizer:
    """Auto-categorize plugins based on keywords."""

    def __init__(self, categories_config: dict):
        self.categories = categories_config.get("categories", {})
        self.default_category = categories_config.get("default", "productivity")

    def categorize(self, plugin: dict) -> str:
        """Determine category based on topics and description."""
        topics = plugin.get("topics", [])
        description = (plugin.get("description", "") or "").lower()
        name = plugin.get("name", "").lower()

        # Combine all text for matching
        text = f"{' '.join(topics)} {description} {name}".lower()

        # Score each category
        scores = {}
        for category, config in self.categories.items():
            keywords = config.get("keywords", [])
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > 0:
                scores[category] = score

        # Return highest scoring category
        if scores:
            return max(scores, key=scores.get)

        return self.default_category


class CatalogBuilder:
    """Build the final catalog from all sources."""

    def __init__(self, github_token: str | None = None):
        self.enricher = GitHubEnricher(github_token)

        # Load configuration files
        self.blacklist = set(load_json_file(BLACKLIST_FILE, []))
        categories_config = load_json_file(CATEGORIES_FILE, self._default_categories())
        self.categorizer = Categorizer(categories_config)

        # Load existing catalog
        self.existing_catalog = load_json_file(CATALOG_FILE, {"plugins": []})
        # Support both legacy "github" and new "github_url" keys for deduplication
        self.existing_plugins = {
            p.get("github_url") or p.get("github", ""): p
            for p in self.existing_catalog.get("plugins", [])
        }

        # Load security reports
        self.security_reports = self._load_security_reports()

        # Load quality scores
        self.quality_scores = self._load_quality_scores()

        # Load health report (optional)
        self.health_report = self._load_health_report()

        # Load archived plugins (for persistence)
        self.archived_plugins = load_json_file(ARCHIVED_PLUGINS_FILE, {"description": "Plugins retirés du catalog actif", "archived": []})

    def _default_categories(self) -> dict:
        """Default category configuration."""
        return {
            "default": "productivity",
            "categories": {
                "business": {
                    "keywords": ["business", "sales", "marketing", "crm", "finance", "startup", "founder", "saas"]
                },
                "engineering": {
                    "keywords": ["engineering", "dev", "development", "code", "programming", "debug", "refactor"]
                },
                "automation": {
                    "keywords": ["automation", "automate", "workflow", "pipeline", "ci", "cd", "deploy"]
                },
                "data": {
                    "keywords": ["data", "analytics", "database", "sql", "query", "etl", "visualization"]
                },
                "design": {
                    "keywords": ["design", "ui", "ux", "css", "style", "theme", "visual"]
                },
                "productivity": {
                    "keywords": ["productivity", "task", "todo", "note", "organize", "manage"]
                },
            }
        }

    def _load_health_report(self) -> dict:
        """Load health report if available."""
        if os.path.exists(HEALTH_REPORT_FILE):
            with open(HEALTH_REPORT_FILE) as f:
                data = json.load(f)
                return data.get("plugins", {})
        return {}

    def _load_security_reports(self) -> dict[str, dict]:
        """Load all security reports."""
        reports = {}
        if os.path.exists(SECURITY_REPORTS_DIR):
            for filename in os.listdir(SECURITY_REPORTS_DIR):
                if filename.endswith('.json'):
                    filepath = os.path.join(SECURITY_REPORTS_DIR, filename)
                    with open(filepath, 'r') as f:
                        report = json.load(f)
                        slug = report.get("plugin_slug", filename[:-5])
                        reports[slug] = report
        return reports

    def _load_quality_scores(self) -> dict[str, dict]:
        """Load all quality scores from data/quality-scores/."""
        scores = {}
        if os.path.exists(QUALITY_SCORES_DIR):
            for filename in os.listdir(QUALITY_SCORES_DIR):
                if filename.endswith('.json'):
                    filepath = os.path.join(QUALITY_SCORES_DIR, filename)
                    try:
                        with open(filepath, 'r') as f:
                            data = json.load(f)
                        slug = filename[:-5]  # strip .json
                        scores[slug] = data
                    except Exception as e:
                        logger.warning("Could not load quality score %s: %s", filename, e)
        return scores

    def _get_quality_info(self, slug: str) -> tuple[int, str, str]:
        """Return (quality_score, quality_grade, review_summary) for a plugin slug."""
        data = self.quality_scores.get(slug, {})
        return (
            data.get("score", 0),
            data.get("grade", "N/A"),
            data.get("recommendation", "") or data.get("review_summary", ""),
        )

    def _is_blacklisted(self, plugin: dict) -> bool:
        """Check if plugin is blacklisted."""
        github_url = plugin.get("github_url", "")
        name = plugin.get("name", "").lower()
        owner = plugin.get("github_owner", "")

        if github_url in self.blacklist:
            return True
        if name in [b.lower() for b in self.blacklist]:
            return True
        if owner in self.blacklist:
            return True

        return False

    def _get_security_score(self, slug: str) -> str:
        """Get security score for a plugin."""
        report = self.security_reports.get(slug, {})
        return report.get("score", "UNKNOWN")

    def _determine_badge(self, plugin: dict, security_score: str) -> str:
        """Determine the badge for a plugin."""
        owner = plugin.get("github_owner", "")

        if owner == "anthropics":
            return "official"
        if security_score == "SAFE":
            return "verified"

        return "community"

    def _enrich_plugin(self, plugin: dict) -> dict:
        """Enrich plugin with fresh GitHub data (requires ENRICH_GITHUB=true)."""
        github_url = plugin.get("github_url", "")
        if not github_url:
            return plugin

        # Parse owner/repo from URL
        parts = github_url.rstrip('/').split('/')
        if len(parts) >= 2:
            owner, repo = parts[-2], parts[-1]

            logger.info("  Enriching: %s/%s", owner, repo)
            repo_info = self.enricher.get_repo_info(owner, repo)

            if repo_info:
                plugin.update({
                    "stars": repo_info.get("stargazers_count", plugin.get("stars", 0)),
                    "forks": repo_info.get("forks_count", plugin.get("forks", 0)),
                    "open_issues": repo_info.get("open_issues_count", plugin.get("open_issues", 0)),
                    "last_commit": repo_info.get("pushed_at", plugin.get("last_commit", "")),
                    "description": repo_info.get("description", plugin.get("description", "")),
                    "topics": repo_info.get("topics", plugin.get("topics", [])),
                })

        return plugin

    def _normalize_plugin(self, plugin: dict) -> dict:
        """Normalize plugin to catalog format."""
        # Read both "github_url" and legacy "github" keys for compatibility
        github_url = plugin.get("github_url") or plugin.get("github", "")
        name = plugin.get("name", "Unknown")
        slug = slugify(name)

        # Get security info
        security_score = self._get_security_score(slug)

        # Get quality info
        quality_score, quality_grade, review_summary = self._get_quality_info(slug)
        # Prefer explicitly stored quality fields on the plugin itself
        quality_score = plugin.get("quality_score", quality_score)
        quality_grade = plugin.get("quality_grade", quality_grade)
        review_summary = plugin.get("review_summary", review_summary)

        # Load health data for this plugin
        health = self.health_report.get(slug, {})
        health_status = health.get("status", plugin.get("health_status", "unknown"))
        days_since_commit = health.get("days_since_commit", plugin.get("days_since_commit"))
        stars_trend = health.get("stars_trend", plugin.get("stars_trend", "stable"))

        # Build normalized plugin — use "github_url" as canonical key
        normalized = {
            "name": name,
            "slug": slug,
            "version": plugin.get("version", "1.0.0"),
            "category": self.categorizer.categorize(plugin),
            "badge": self._determine_badge(plugin, security_score),
            "description": plugin.get("description", ""),
            "github_url": github_url,
            "stars": plugin.get("stars", 0),
            "forks": plugin.get("forks", 0),
            "open_issues": plugin.get("open_issues", 0),
            "topics": plugin.get("topics", []),
            "last_commit": plugin.get("last_commit", ""),
            "plugin_type": plugin.get("plugin_type", "unknown"),
            "security_score": security_score,
            "quality_score": quality_score,
            "quality_grade": quality_grade,
            "review_summary": review_summary,
            "added": plugin.get("added", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            "status": plugin.get("status", "active"),
            "health_status": health_status,
            "days_since_commit": days_since_commit,
            "stars_trend": stars_trend,
            "tags": plugin.get("tags", plugin.get("topics", [])),
        }

        return normalized

    def build(self) -> dict:
        """Build the complete catalog."""
        logger.info("Building catalog...")

        all_plugins = {}  # Keyed by github_url for deduplication

        # 1. Load existing catalog plugins
        logger.info("Loading existing catalog...")
        for plugin in self.existing_catalog.get("plugins", []):
            # Support both legacy "github" and new "github_url" keys
            github_url = plugin.get("github_url") or plugin.get("github", "")
            if github_url:
                all_plugins[github_url] = plugin

        # 2. Load new plugins from scanner (with JSON validation)
        logger.info("Loading new plugins...")
        try:
            new_plugins_data = load_json_file(NEW_PLUGINS_FILE, {"plugins": []})
            if not isinstance(new_plugins_data, dict) or "plugins" not in new_plugins_data:
                logger.error("Invalid format in %s: expected dict with 'plugins' key, skipping", NEW_PLUGINS_FILE)
                new_plugins_data = {"plugins": []}
            elif not isinstance(new_plugins_data["plugins"], list):
                logger.error("Invalid 'plugins' field in %s: expected list, skipping", NEW_PLUGINS_FILE)
                new_plugins_data = {"plugins": []}
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Corrupted JSON in %s: %s, skipping", NEW_PLUGINS_FILE, e)
            new_plugins_data = {"plugins": []}

        for plugin in new_plugins_data.get("plugins", []):
            github_url = plugin.get("github_url", "")
            if github_url:
                # Merge with existing or add new
                if github_url in all_plugins:
                    # Update existing with new data
                    existing = all_plugins[github_url]
                    existing.update({
                        "stars": plugin.get("stars", existing.get("stars", 0)),
                        "forks": plugin.get("forks", existing.get("forks", 0)),
                        "open_issues": plugin.get("open_issues", existing.get("open_issues", 0)),
                        "last_commit": plugin.get("last_commit", existing.get("last_commit", "")),
                        "topics": plugin.get("topics", existing.get("topics", [])),
                    })
                else:
                    all_plugins[github_url] = plugin

        # 3. Process and filter plugins
        logger.info("Processing plugins...")
        final_plugins = []
        filtered_blacklist = 0
        filtered_danger = 0
        filtered_dead = 0
        newly_archived_slugs = []

        for github_url, plugin in all_plugins.items():
            # Normalize (includes health fields)
            normalized = self._normalize_plugin(plugin)

            # Check blacklist
            if self._is_blacklisted(normalized):
                logger.info("  Filtered (blacklist): %s", normalized['name'])
                filtered_blacklist += 1
                continue

            # Check security score
            if normalized.get("security_score") == "DANGER":
                logger.info("  Filtered (danger): %s", normalized['name'])
                filtered_danger += 1
                continue

            # Health: exclude dead plugins, archive them
            if normalized.get("health_status") == "dead":
                logger.info("  Filtered (dead): %s", normalized['name'])
                filtered_dead += 1
                self._archive_dead_plugin(normalized)
                continue

            # Health: track newly archived plugins
            if normalized.get("health_status") == "archived":
                existing_slugs = [
                    p.get("slug") for p in self.archived_plugins.get("archived", [])
                    if isinstance(p, dict)
                ]
                if normalized["slug"] not in existing_slugs:
                    newly_archived_slugs.append(normalized["slug"])

            # Enrich with fresh GitHub data if ENRICH_GITHUB=true
            if ENRICH_GITHUB:
                normalized = self._enrich_plugin(normalized)

            final_plugins.append(normalized)

        # Save updated archived-plugins list
        save_json_file(ARCHIVED_PLUGINS_FILE, self.archived_plugins)

        if filtered_dead:
            logger.info("  Archived %d dead plugin(s) to %s", filtered_dead, ARCHIVED_PLUGINS_FILE)
        if newly_archived_slugs:
            logger.info("  Newly archived plugins: %s", ", ".join(newly_archived_slugs))

        # 4. Sort by weighted score: quality_score * 0.3 + stars * 0.7
        def _weighted_sort_key(p: dict) -> float:
            q = p.get("quality_score", 0) or 0
            s = p.get("stars", 0) or 0
            s_norm = min(s / 5.0, 100.0)
            return q * 0.3 + s_norm * 0.7

        final_plugins.sort(key=_weighted_sort_key, reverse=True)

        # 5. Build category stats
        category_stats = {}
        for plugin in final_plugins:
            cat = plugin.get("category", "productivity")
            category_stats[cat] = category_stats.get(cat, 0) + 1

        # 6. Build final catalog
        catalog = {
            "version": "1.0.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "plugins": final_plugins,
            "stats": {
                "total_plugins": len(final_plugins),
                "categories": category_stats,
                "last_scan": new_plugins_data.get("scan_date", ""),
                "filtered": {
                    "blacklist": filtered_blacklist,
                    "danger": filtered_danger,
                    "dead": filtered_dead,
                },
                "newly_archived": newly_archived_slugs,
            }
        }

        return catalog

    def _archive_dead_plugin(self, plugin: dict) -> None:
        """Move a dead plugin to the archived-plugins.json list."""
        archived_list = self.archived_plugins.setdefault("archived", [])
        slugs = [p.get("slug") for p in archived_list if isinstance(p, dict)]
        if plugin.get("slug") not in slugs:
            archived_list.append({
                "slug": plugin.get("slug"),
                "name": plugin.get("name"),
                "github_url": plugin.get("github_url"),
                "archived_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "reason": "dead",
            })


def main():
    logger.info("=" * 60)
    logger.info("PlugVault Catalog Builder")
    logger.info("=" * 60)

    # Get GitHub token (optional)
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        logger.info("GITHUB_TOKEN not set. GitHub enrichment will be limited.")

    if ENRICH_GITHUB:
        logger.info("ENRICH_GITHUB=true: GitHub enrichment enabled.")
    else:
        logger.info("ENRICH_GITHUB not set: GitHub enrichment disabled. Set ENRICH_GITHUB=true to enable.")

    # Build catalog
    builder = CatalogBuilder(github_token)
    catalog = builder.build()

    # Save catalog
    save_json_file(CATALOG_FILE, catalog)

    logger.info("=" * 60)
    logger.info("Catalog build complete!")
    logger.info("  Total plugins: %d", catalog['stats']['total_plugins'])
    logger.info("  Categories: %d", len(catalog['stats']['categories']))
    logger.info("  Filtered (blacklist): %d", catalog['stats']['filtered']['blacklist'])
    logger.info("  Filtered (danger): %d", catalog['stats']['filtered']['danger'])
    logger.info("  Filtered (dead): %d", catalog['stats']['filtered'].get('dead', 0))
    if catalog['stats'].get('newly_archived'):
        logger.info("  Newly archived: %s", ", ".join(catalog['stats']['newly_archived']))
    logger.info("  Output: %s", CATALOG_FILE)
    logger.info("=" * 60)

    # Print category breakdown
    logger.info("Category breakdown:")
    for cat, count in sorted(catalog['stats']['categories'].items()):
        logger.info("  %s: %d", cat, count)

    sys.exit(0)


if __name__ == "__main__":
    main()
