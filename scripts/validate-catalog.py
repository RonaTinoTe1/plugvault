#!/usr/bin/env python3
"""
=============================================================
PLUGVAULT — Catalog Validator
=============================================================
Validates catalog.json against the PlugVault schema.

Checks:
  - Required fields on every plugin
  - Category values against data/categories.json
  - Badge values (official / verified / community)
  - github_url format (valid URL or empty string)
  - Stats consistency (totals match actual counts)

Usage:
    python scripts/validate-catalog.py

Exit codes:
    0  All checks passed
    1  Validation errors found
=============================================================
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FIELDS = ["name", "slug", "category", "badge", "status", "description"]
OPTIONAL_URL_FIELDS = ["github_url", "readme_url"]
VALID_BADGES = {"official", "verified", "community"}
VALID_STATUSES = {"active", "inactive", "deprecated", "pending_review"}
URL_PATTERN = re.compile(r"^https?://[^\s]+$")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"FATAL: Invalid JSON in {path}: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"FATAL: File not found: {path}")
        sys.exit(1)


def load_valid_categories():
    cats_path = ROOT / "data" / "categories.json"
    data = load_json(cats_path)
    return set(data.get("categories", {}).keys())


def validate_plugin(plugin, index, valid_categories):
    errors = []
    prefix = f"plugins[{index}] ({plugin.get('name', '???')})"

    for field in REQUIRED_FIELDS:
        if field not in plugin:
            errors.append(f"{prefix}: missing required field '{field}'")
        elif not plugin[field]:
            errors.append(f"{prefix}: field '{field}' is empty")

    if "category" in plugin and plugin["category"] not in valid_categories:
        errors.append(
            f"{prefix}: category '{plugin['category']}' not in allowed list "
            f"({', '.join(sorted(valid_categories))})"
        )

    if "badge" in plugin and plugin["badge"] not in VALID_BADGES:
        errors.append(
            f"{prefix}: badge '{plugin['badge']}' not valid "
            f"(expected: {', '.join(sorted(VALID_BADGES))})"
        )

    if "status" in plugin and plugin["status"] not in VALID_STATUSES:
        errors.append(
            f"{prefix}: status '{plugin['status']}' not valid "
            f"(expected: {', '.join(sorted(VALID_STATUSES))})"
        )

    for url_field in OPTIONAL_URL_FIELDS:
        value = plugin.get(url_field, "")
        if value and not URL_PATTERN.match(value):
            errors.append(f"{prefix}: '{url_field}' is not a valid URL: {value}")

    slug = plugin.get("slug", "")
    if slug and not re.match(r"^[a-z0-9][a-z0-9\-]*$", slug):
        errors.append(f"{prefix}: slug '{slug}' must be lowercase alphanumeric with hyphens")

    for num_field in ["downloads", "weekly_downloads", "skills", "commands"]:
        val = plugin.get(num_field)
        if val is not None and (not isinstance(val, int) or val < 0):
            errors.append(f"{prefix}: '{num_field}' must be a non-negative integer")

    return errors


def validate_stats(catalog, valid_categories):
    errors = []
    stats = catalog.get("stats", {})
    plugins = catalog.get("plugins", [])

    declared_total = stats.get("total_plugins", 0)
    actual_total = len(plugins)
    if declared_total != actual_total:
        errors.append(
            f"stats.total_plugins is {declared_total} but found {actual_total} plugins"
        )

    declared_downloads = stats.get("total_downloads", 0)
    actual_downloads = sum(p.get("downloads", 0) for p in plugins)
    if declared_downloads != actual_downloads:
        errors.append(
            f"stats.total_downloads is {declared_downloads} but sum is {actual_downloads}"
        )

    return errors


def main():
    catalog_path = ROOT / "catalog.json"
    catalog = load_json(catalog_path)
    valid_categories = load_valid_categories()

    all_errors = []
    all_warnings = []

    if "version" not in catalog:
        all_warnings.append("catalog.json missing 'version' field")
    if "last_updated" not in catalog:
        all_warnings.append("catalog.json missing 'last_updated' field")

    plugins = catalog.get("plugins", [])
    if not plugins:
        all_warnings.append("catalog.json has no plugins")

    slugs = []
    for i, plugin in enumerate(plugins):
        all_errors.extend(validate_plugin(plugin, i, valid_categories))
        slug = plugin.get("slug")
        if slug:
            if slug in slugs:
                all_errors.append(f"Duplicate slug: '{slug}'")
            slugs.append(slug)

    all_errors.extend(validate_stats(catalog, valid_categories))

    print("=" * 60)
    print("PLUGVAULT CATALOG VALIDATION REPORT")
    print("=" * 60)
    print(f"Catalog: {catalog_path}")
    print(f"Plugins: {len(plugins)}")
    print(f"Categories loaded: {len(valid_categories)}")
    print()

    if all_warnings:
        print(f"WARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  ⚠ {w}")
        print()

    if all_errors:
        print(f"ERRORS ({len(all_errors)}):")
        for e in all_errors:
            print(f"  ✗ {e}")
        print()
        print("RESULT: FAILED")
        sys.exit(1)
    else:
        print("RESULT: PASSED ✓")
        print("All plugins are valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
