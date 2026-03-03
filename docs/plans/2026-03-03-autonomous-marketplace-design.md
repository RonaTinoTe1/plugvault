# PlugVault Autonomous Marketplace Design

**Date**: 2026-03-03
**Status**: Approved

## Overview

Transform PlugVault from a static mockup into a fully autonomous plugin marketplace that:
- Automatically scans GitHub for real Claude plugins
- Analyzes and categorizes plugins intelligently
- Verifies security with pattern matching + VirusTotal
- Updates the site automatically via GitHub Actions
- Requires zero manual maintenance

## Architecture

```
plugvault/
├── index.html                    # Site (fetches catalog.json)
├── catalog.json                  # Auto-generated plugin catalog
├── .github/
│   ├── workflows/
│   │   ├── scan-plugins.yml      # Weekly GitHub scan (Sunday 20h)
│   │   ├── security-check.yml    # Security + VirusTotal (on PR + weekly)
│   │   ├── update-catalog.yml    # Build catalog (Monday 8h + after merge)
│   │   └── deploy.yml            # GitHub Pages deploy
│   └── ISSUE_TEMPLATE/
│       └── plugin-submission.yml # Submission form
├── scripts/
│   ├── scan-github.py            # GitHub API scanner
│   ├── security-scanner.py       # Pattern scan + VirusTotal
│   ├── build-catalog.py          # Generate catalog.json
│   └── requirements.txt          # Python deps (requests, vt-py)
├── data/
│   ├── sources.json              # Scan sources (exists)
│   ├── categories.json           # Dynamic category definitions
│   ├── blacklist.json            # Blocked plugins
│   └── security-reports/         # Per-plugin security reports
└── README.md
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GitHub API Auth | GITHUB_TOKEN | 5000 requests/hour, auto-provided in Actions |
| Security Scanning | Lightweight + VirusTotal | Catches 90% issues + external verification |
| Installation Methods | All methods | Marketplace, standalone, git clone, MCP |
| README Display | Fetch on demand | No storage, always current |
| Categories | Dynamic AI categorization | Flexible, grows organically |
| Implementation | Parallel agent team | Fastest for independent components |

## Data Flow

```
GitHub API/Awesome Lists
        │
        v
  scan-github.py ──> new-plugins.json
        │
        v
  security-scanner.py ──> security-reports/
        │
        v
  build-catalog.py ──> catalog.json
        │
        v
  index.html ──> GitHub Pages
```

## Components

### 1. Python Scripts

**scan-github.py**
- Uses GitHub REST API with GITHUB_TOKEN
- Searches: topics (claude-plugin, claude-code-plugin, claude-mcp)
- Scrapes awesome-lists from sources.json
- Filters: > 2 stars, last commit < 90 days
- Output: data/new-plugins.json

**security-scanner.py**
- Clones repos (shallow, depth=1)
- Pattern matching for:
  - Credentials (API keys, tokens, passwords)
  - Dangerous functions (eval, exec, subprocess shell=True)
  - Suspicious URLs (pastebin, ngrok, ip addresses)
  - Binary files > 1MB
- VirusTotal integration:
  - Check repo URL reputation
  - Scan binary files
- Output: data/security-reports/<plugin>.json with score SAFE/CAUTION/DANGER

**build-catalog.py**
- Merges all plugin sources
- Deduplicates by GitHub URL
- Enriches with GitHub API (stars, forks, issues, last commit)
- Auto-categorizes based on topics + description + README
- Filters blacklisted and DANGER-scored plugins
- Output: catalog.json

### 2. GitHub Actions

**scan-plugins.yml** (Sunday 20h)
- Checkout repo
- Run scan-github.py
- If new plugins: create PR with additions

**security-check.yml** (on PR + weekly)
- For each plugin in PR/catalog:
  - Clone repo
  - Run security-scanner.py
  - Generate security report
- Update security scores in catalog

**update-catalog.yml** (Monday 8h + after merge)
- Run build-catalog.py
- Commit + push catalog.json
- Trigger deploy

**deploy.yml** (on push to main)
- GitHub Pages deployment

### 3. Frontend (index.html)

**Plugin Cards**
- Fetch catalog.json on load
- Render cards with real data (name, description, stars, badge)
- Badges: Official (anthropics/), Verified (SAFE score), Community

**Plugin Detail Modal**
- Fetch README from GitHub raw URL on demand
- Display: README, install commands, GitHub link, stats, security score
- Report issue button

**Install Button**
- Copy installation command to clipboard
- Show all methods: marketplace, standalone, git clone, MCP
- Toast notification

**Search & Filters**
- Full-text search on name, description, tags
- Dynamic category filters from catalog
- Sort by: stars, date added, last update, name

**Submit Form**
- Redirect to GitHub Issues with pre-filled template

### 4. Security Scanner Patterns

```python
PATTERNS = {
    "credentials": [
        r"(?i)(api_key|apikey|api_secret|secret_key)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)(token|auth)\s*=\s*['\"][^'\"]+['\"]",
        r"sk-[a-zA-Z0-9]{20,}",  # OpenAI keys
        r"xox[baprs]-[a-zA-Z0-9-]+",  # Slack tokens
    ],
    "dangerous_functions": [
        r"eval\s*\(",
        r"exec\s*\(",
        r"subprocess\..*shell\s*=\s*True",
        r"os\.system\s*\(",
        r"compile\s*\(.*exec",
    ],
    "suspicious_urls": [
        r"https?://pastebin\.com",
        r"https?://ngrok\.io",
        r"https?://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+",
        r"https?://discord\.com/api/webhooks",
    ]
}
```

### 5. VirusTotal Integration

- API Key stored as `VT_API_KEY` GitHub secret
- Check repo URL reputation (quick, 1 request)
- Scan binary files > 1MB (upload + check)
- Rate limit: 4 requests/min (free tier)
- Fallback gracefully if VT unavailable

## catalog.json Schema

```json
{
  "version": "1.0.0",
  "last_updated": "2026-03-03T20:00:00Z",
  "plugins": [
    {
      "id": "forge",
      "name": "FORGE",
      "description": "...",
      "github_url": "https://github.com/user/plugin",
      "github_owner": "user",
      "github_repo": "plugin",
      "stars": 150,
      "forks": 23,
      "open_issues": 5,
      "last_commit": "2026-02-28T10:00:00Z",
      "category": "business",
      "tags": ["saas", "founder"],
      "badge": "official|verified|community",
      "security_score": "SAFE|CAUTION|DANGER",
      "plugin_type": "plugin|mcp|hooks|mixed",
      "skills": 6,
      "commands": 10,
      "added_date": "2026-03-01",
      "readme_url": "https://raw.githubusercontent.com/user/plugin/main/README.md"
    }
  ],
  "stats": {
    "total_plugins": 100,
    "categories": {
      "business": 15,
      "engineering": 30,
      "automation": 20,
      "data": 15,
      "design": 10,
      "productivity": 10
    },
    "last_scan": "2026-03-03T20:00:00Z"
  }
}
```

## GitHub Secrets Required

| Secret | Purpose |
|--------|---------|
| `GITHUB_TOKEN` | Auto-provided by Actions |
| `VT_API_KEY` | VirusTotal API (optional, enhances security) |

## Success Criteria

- [ ] Site displays 100+ real plugins with accurate data
- [ ] Weekly scan discovers new plugins automatically
- [ ] Security scanner catches common malicious patterns
- [ ] VirusTotal integration verifies repo safety
- [ ] Plugin detail modal shows README + install commands
- [ ] Install button copies correct command to clipboard
- [ ] Submit form creates GitHub Issue
- [ ] Zero manual maintenance required
