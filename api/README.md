# PlugVault Public API

A read-only static REST API automatically generated from the plugin catalog.

**Base URL:** `https://<username>.github.io/plugvault/api/v1/`

> The API is regenerated on every catalog build (typically weekly).
> All responses are static JSON files served via GitHub Pages.

---

## Endpoints

### `GET /api/v1/plugins.json`
Paginated plugin list — first page (up to 20 plugins).

**Response:**
```json
{
  "version": "1",
  "total": 42,
  "page": 1,
  "per_page": 20,
  "pages": 3,
  "data": [ ...plugins... ],
  "meta": {
    "last_updated": "2026-03-03T08:00:00+00:00",
    "next_page": "api/v1/plugins-2.json"
  }
}
```

**Additional pages:** `GET /api/v1/plugins-2.json`, `/api/v1/plugins-3.json`, etc.

---

### `GET /api/v1/plugins/{slug}.json`
Full detail for a single plugin.

**Example:** `GET /api/v1/plugins/forge.json`

```json
{
  "name": "FORGE",
  "slug": "forge",
  "version": "2.0.0",
  "category": "business",
  "badge": "official",
  "description": "Full-stack solo founder toolkit...",
  "github_url": "https://github.com/user/forge",
  "stars": 120,
  "forks": 14,
  "topics": ["saas", "founder"],
  "last_commit": "2026-02-28T12:00:00Z",
  "security_score": "SAFE",
  "discovered_via": "manual",
  "added": "2026-03-03"
}
```

---

### `GET /api/v1/categories.json`
All categories with plugin counts and descriptions.

```json
{
  "categories": [
    {
      "name": "engineering",
      "count": 12,
      "description": "Developer tools, code generation, debugging..."
    }
  ]
}
```

---

### `GET /api/v1/stats.json`
Aggregate catalog statistics.

```json
{
  "total_plugins": 42,
  "total_categories": 11,
  "last_updated": "2026-03-03T08:00:00+00:00",
  "last_scan": "2026-03-02T06:00:00+00:00",
  "by_category": {
    "engineering": 12,
    "business": 8
  },
  "by_badge": {
    "official": 1,
    "verified": 20,
    "community": 21
  },
  "by_security": {
    "SAFE": 35,
    "CAUTION": 5,
    "UNKNOWN": 2
  },
  "avg_quality_score": 72
}
```

---

### `GET /api/v1/featured.json`
Featured plugins only.

```json
{
  "featured": [ ...plugins... ],
  "total": 3,
  "last_updated": "2026-03-03T08:00:00+00:00"
}
```

---

### `GET /api/v1/search-index.json`
Lightweight index for client-side full-text search.

```json
{
  "index": [
    {
      "slug": "forge",
      "name": "FORGE",
      "description": "Full-stack solo founder toolkit...",
      "tags": ["saas", "founder"],
      "category": "business",
      "badge": "official",
      "security_score": "SAFE",
      "stars": 120,
      "github_url": "https://github.com/user/forge",
      "discovered_via": "manual"
    }
  ]
}
```

Use this endpoint instead of the full catalog for search features — it is significantly smaller.

---

## Plugin Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name |
| `slug` | string | URL-safe identifier |
| `version` | string | Plugin version |
| `category` | string | Category (engineering, business, ...) |
| `badge` | string | `official`, `verified`, or `community` |
| `description` | string | Short description |
| `github_url` | string | GitHub repository URL |
| `stars` | number | GitHub stars |
| `forks` | number | GitHub forks |
| `topics` | array | GitHub repository topics |
| `tags` | array | Plugin tags |
| `last_commit` | string | ISO 8601 date of last commit |
| `security_score` | string | `SAFE`, `CAUTION`, `DANGER`, or `UNKNOWN` |
| `discovered_via` | string | How the plugin was found |
| `added` | string | Date added to catalog (YYYY-MM-DD) |
| `featured` | boolean | Whether the plugin is featured |

---

## `discovered_via` Values

| Value | Meaning |
|-------|---------|
| `github-search` | Found via GitHub repository search |
| `awesome-list` | Found in an awesome-list README |
| `code-search` | Found via GitHub code search |
| `manual` | Manually added by maintainers |

---

## Refresh Cadence

The API files are regenerated automatically:
- **Weekly** (every Monday at 08:00 UTC) via the `Update Catalog` GitHub Action
- On every push that modifies `data/new-plugins.json` or security reports
- On manual workflow dispatch

---

## Usage Examples

### curl

```bash
# Get catalog stats
curl https://<username>.github.io/plugvault/api/v1/stats.json

# Get first page of plugins
curl https://<username>.github.io/plugvault/api/v1/plugins.json

# Get a specific plugin
curl https://<username>.github.io/plugvault/api/v1/plugins/forge.json

# Get all categories
curl https://<username>.github.io/plugvault/api/v1/categories.json
```

### JavaScript (fetch)

```javascript
// Load stats
const stats = await fetch('https://<username>.github.io/plugvault/api/v1/stats.json')
  .then(r => r.json());
console.log(`${stats.total_plugins} plugins indexed`);

// Search using the lightweight index
const { index } = await fetch('https://<username>.github.io/plugvault/api/v1/search-index.json')
  .then(r => r.json());
const results = index.filter(p =>
  `${p.name} ${p.description} ${p.tags.join(' ')}`.toLowerCase().includes('security')
);

// Paginate through all plugins
async function fetchAllPlugins() {
  const plugins = [];
  let url = 'https://<username>.github.io/plugvault/api/v1/plugins.json';
  while (url) {
    const page = await fetch(url).then(r => r.json());
    plugins.push(...page.data);
    url = page.meta.next_page
      ? `https://<username>.github.io/plugvault/${page.meta.next_page}`
      : null;
  }
  return plugins;
}

// Get a specific plugin by slug
const forge = await fetch('https://<username>.github.io/plugvault/api/v1/plugins/forge.json')
  .then(r => r.json());
```

---

## Notes

- All endpoints return `Content-Type: application/json`
- CORS is open (GitHub Pages allows all origins)
- No authentication required — the API is fully public
- Rate limits depend on GitHub Pages (no enforced limit for read access)
- To build the API locally: `python scripts/build-api.py --catalog catalog.json --output-dir api/v1/`
