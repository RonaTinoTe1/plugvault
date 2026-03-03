#!/usr/bin/env python3
"""
API Builder for PlugVault
Generates a static REST API from catalog.json.

Usage:
  python scripts/build-api.py --catalog catalog.json --output-dir api/v1/
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any


PER_PAGE = 20

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "engineering": "Developer tools, code generation, debugging, and software engineering",
    "business": "Business workflows, startup tools, sales, and entrepreneurship",
    "automation": "CI/CD, task automation, workflow pipelines, and deployment",
    "data": "Analytics, databases, data transformation, and visualization",
    "design": "UI/UX, CSS, design systems, and visual tooling",
    "productivity": "Task management, organization, note-taking, and focus tools",
    "security": "Security scanning, auditing, vulnerability detection",
    "testing": "Test generation, QA automation, and coverage tools",
    "devops": "Infrastructure, containers, monitoring, and cloud operations",
    "ai": "AI integrations, LLM tooling, and model orchestration",
    "devtools": "Development utilities, linters, formatters, and editors",
}


def slugify(name: str) -> str:
    """Convert name to URL-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9\-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def load_catalog(path: str) -> dict[str, Any]:
    """Load catalog.json, returning empty structure if file is missing or empty."""
    if not os.path.exists(path):
        return {"version": "1.0.0", "last_updated": "", "plugins": [], "stats": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"version": "1.0.0", "last_updated": "", "plugins": [], "stats": {}}
    return data


def write_json(path: str, data: Any) -> None:
    """Write data to a JSON file with UTF-8 encoding, creating parent dirs."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Written: {path}")


def build_plugins_pages(plugins: list[dict], output_dir: str, last_updated: str) -> None:
    """Generate paginated plugins.json (and plugins-N.json) files."""
    total = len(plugins)
    total_pages = max(1, math.ceil(total / PER_PAGE))

    for page in range(1, total_pages + 1):
        start = (page - 1) * PER_PAGE
        end = start + PER_PAGE
        page_data = plugins[start:end]

        next_page = f"api/v1/plugins-{page + 1}.json" if page < total_pages else None

        payload: dict[str, Any] = {
            "version": "1",
            "total": total,
            "page": page,
            "per_page": PER_PAGE,
            "pages": total_pages,
            "data": page_data,
            "meta": {
                "last_updated": last_updated,
                "next_page": next_page,
            },
        }

        filename = "plugins.json" if page == 1 else f"plugins-{page}.json"
        write_json(os.path.join(output_dir, filename), payload)


def build_plugin_detail_pages(plugins: list[dict], output_dir: str) -> None:
    """Generate one JSON file per plugin under plugins/{slug}.json."""
    plugins_dir = os.path.join(output_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)

    for plugin in plugins:
        slug = plugin.get("slug") or slugify(plugin.get("name", "unknown"))
        write_json(os.path.join(plugins_dir, f"{slug}.json"), plugin)


def build_categories(plugins: list[dict], output_dir: str) -> None:
    """Generate categories.json with per-category counts and descriptions."""
    counts: dict[str, int] = {}
    for plugin in plugins:
        cat = plugin.get("category") or "productivity"
        counts[cat] = counts.get(cat, 0) + 1

    categories = [
        {
            "name": cat,
            "count": count,
            "description": CATEGORY_DESCRIPTIONS.get(cat, ""),
        }
        for cat, count in sorted(counts.items(), key=lambda x: -x[1])
    ]

    write_json(os.path.join(output_dir, "categories.json"), {"categories": categories})


def build_stats(catalog: dict, plugins: list[dict], output_dir: str) -> None:
    """Generate stats.json with aggregate metrics."""
    by_category: dict[str, int] = {}
    by_badge: dict[str, int] = {"official": 0, "verified": 0, "community": 0}
    by_security: dict[str, int] = {}
    quality_scores: list[float] = []

    for plugin in plugins:
        cat = plugin.get("category") or "productivity"
        by_category[cat] = by_category.get(cat, 0) + 1

        badge = (plugin.get("badge") or "community").lower()
        by_badge[badge] = by_badge.get(badge, by_badge.get("community", 0)) + 1

        sec = plugin.get("security_score") or "UNKNOWN"
        by_security[sec] = by_security.get(sec, 0) + 1

        qs = plugin.get("quality_score")
        if isinstance(qs, (int, float)):
            quality_scores.append(float(qs))

    avg_quality = round(sum(quality_scores) / len(quality_scores)) if quality_scores else 0

    catalog_stats = catalog.get("stats") or {}
    stats: dict[str, Any] = {
        "total_plugins": len(plugins),
        "total_categories": len(by_category),
        "last_updated": catalog.get("last_updated") or "",
        "last_scan": catalog_stats.get("last_scan") or "",
        "by_category": by_category,
        "by_badge": by_badge,
        "by_security": by_security,
        "avg_quality_score": avg_quality,
    }

    write_json(os.path.join(output_dir, "stats.json"), stats)


def build_featured(plugins: list[dict], output_dir: str, last_updated: str) -> None:
    """Generate featured.json with only featured plugins."""
    featured = [p for p in plugins if p.get("featured")]
    write_json(
        os.path.join(output_dir, "featured.json"),
        {
            "featured": featured,
            "total": len(featured),
            "last_updated": last_updated,
        },
    )


def build_search_index(plugins: list[dict], output_dir: str) -> None:
    """Generate search-index.json — a lightweight index for client-side full-text search."""
    index = [
        {
            "slug": p.get("slug") or slugify(p.get("name", "unknown")),
            "name": p.get("name") or "",
            "description": p.get("description") or "",
            "tags": p.get("tags") or [],
            "category": p.get("category") or "",
            "badge": p.get("badge") or "",
            "security_score": p.get("security_score") or "",
            "stars": p.get("stars") or 0,
            "github_url": p.get("github_url") or "",
            "discovered_via": p.get("discovered_via") or "",
        }
        for p in plugins
    ]

    write_json(os.path.join(output_dir, "search-index.json"), {"index": index})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build PlugVault static REST API from catalog.json"
    )
    parser.add_argument(
        "--catalog",
        default="catalog.json",
        help="Path to catalog.json (default: catalog.json)",
    )
    parser.add_argument(
        "--output-dir",
        default="api/v1/",
        help="Output directory for generated API files (default: api/v1/)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("PlugVault API Builder")
    print("=" * 60)
    print(f"  Catalog:    {args.catalog}")
    print(f"  Output dir: {args.output_dir}")

    catalog = load_catalog(args.catalog)
    plugins = catalog.get("plugins") or []
    last_updated = catalog.get("last_updated") or datetime.now(timezone.utc).isoformat()

    print(f"  Plugins:    {len(plugins)}")
    print()
    print("Generating API files...")

    os.makedirs(args.output_dir, exist_ok=True)

    build_plugins_pages(plugins, args.output_dir, last_updated)
    build_plugin_detail_pages(plugins, args.output_dir)
    build_categories(plugins, args.output_dir)
    build_stats(catalog, plugins, args.output_dir)
    build_featured(plugins, args.output_dir, last_updated)
    build_search_index(plugins, args.output_dir)

    print()
    print("=" * 60)
    print("API build complete!")
    print(f"  {len(plugins)} plugin(s) indexed")
    print(f"  Output: {args.output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
