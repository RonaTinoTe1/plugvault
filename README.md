# PlugVault - Autonomous Claude Plugin Marketplace

A fully autonomous marketplace for Claude Code and Claude Cowork plugins.

## Features

- **100+ Real Plugins**: Scans GitHub for actual Claude plugins
- **Auto-Discovery**: Weekly scans find new plugins automatically
- **Security Checks**: Pattern matching + VirusTotal integration
- **Smart Categorization**: AI-powered category assignment
- **One-Click Install**: Copy installation commands to clipboard

## How It Works

1. **Weekly Scan** (Sundays 20h UTC): Scans GitHub API and awesome-lists for new plugins
2. **Security Check** (Mondays 3h UTC): Analyzes plugins for malicious patterns
3. **Catalog Update** (Mondays 8h UTC): Builds the final catalog.json
4. **Auto Deploy**: GitHub Pages updates automatically

## Submit a Plugin

1. Go to the [Submit](#submit) section on the site
2. Fill out the form with your plugin details
3. A GitHub Issue will be created
4. Your plugin will be reviewed and added automatically

## For Developers

### GitHub Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `GITHUB_TOKEN` | Auto | Provided by GitHub Actions |
| `VT_API_KEY` | Optional | VirusTotal API key for enhanced security |

### Local Development

```bash
# Install dependencies
pip install -r scripts/requirements.txt

# Run scanner
GITHUB_TOKEN=your_token python scripts/scan-github.py

# Run security check
VT_API_KEY=your_key python scripts/security-scanner.py pluginslug

# Build catalog
GITHUB_TOKEN=your_token python scripts/build-catalog.py

# Serve locally
python -m http.server 8000
```

## Architecture

See [docs/plans/2026-03-03-autonomous-marketplace-design.md](docs/plans/2026-03-03-autonomous-marketplace-design.md) for full design documentation.

## License

MIT
