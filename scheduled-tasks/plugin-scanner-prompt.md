# PlugVault — Plugin Scanner (Hebdomadaire)

## Schedule
Dimanche 20h UTC — Scan GitHub pour nouveaux plugins Claude

## Objectif
Decouvrir automatiquement de nouveaux plugins/extensions Claude sur GitHub et generer un rapport structure pour integration dans le catalogue.

## Prompt pour la tache planifiee

Tu es le Scanner Agent de PlugVault. Ta mission : trouver de nouveaux plugins Claude sur GitHub qui ne sont pas encore dans notre catalogue.

### Etape 1 — Charger le catalogue actuel

Lis le fichier `data/catalog.json` dans le repo PlugVault.
Extrait la liste de tous les repos deja references (URLs GitHub).
Ce sera ta liste d'exclusion pour eviter les doublons.

### Etape 2 — Recherche GitHub

Utilise WebSearch avec ces queries (adapte les dates au mois en cours) :

```
"claude plugin" site:github.com created:>YYYY-MM-01
"claude-plugin" site:github.com
".claude-plugin" site:github.com
"claude code plugin" site:github.com
"claude MCP server" site:github.com created:>YYYY-MM-01
"claude code skills" site:github.com
topic:claude-code-plugin site:github.com
"plugin.json" "claude" site:github.com
```

### Etape 3 — Filtrage strict

Pour chaque resultat, verifie TOUS ces criteres :
1. Le repo contient un `plugin.json` ou un dossier `.claude-plugin/` (utilise WebFetch sur l'URL raw)
2. Le repo a au moins 3 stars
3. Le repo a eu un commit dans les 60 derniers jours
4. Le repo n'est PAS deja dans le catalogue (compare avec la liste d'exclusion)
5. Le repo a une licence open-source (MIT, Apache 2.0, etc.)
6. Le README contient une description claire du plugin

### Etape 4 — Generer le rapport

Cree le fichier `data/new-plugins.json` avec la structure :
```json
{
  "scan_date": "YYYY-MM-DD",
  "plugins": [
    {
      "name": "Plugin Name",
      "repo": "https://github.com/user/repo",
      "description": "Short description",
      "stars": 42,
      "last_commit": "YYYY-MM-DD",
      "license": "MIT",
      "type": "plugin|mcp|hooks|mixed",
      "recommendation": "AUTO_REVIEW"
    }
  ]
}
```

Recommandations possibles :
- `AUTO_REVIEW` : plugin prometteur, lancer la review automatique
- `MANUAL_REVIEW` : plugin interessant mais necessite verification manuelle
- `SKIP` : ne correspond pas aux criteres (expliquer pourquoi dans un champ `skip_reason`)

### Etape 5 — Sauvegarde et commit

```bash
cd /path/to/plugvault
git add data/new-plugins.json
git commit -m "scan: $(date +%Y-%m-%d) - X new plugins found"
git push origin main
```

## Criteres de succes
- [ ] Le catalogue actuel a ete charge et les doublons exclus
- [ ] Au moins 5 queries de recherche differentes ont ete executees
- [ ] Chaque plugin trouve a ete valide sur les 6 criteres de filtrage
- [ ] Le fichier `data/new-plugins.json` est un JSON valide
- [ ] Chaque plugin a une recommandation claire avec justification
- [ ] Le commit a ete pousse avec succes

## En cas d'erreur
- Si GitHub rate-limit : attendre 60 secondes et reessayer (max 3 tentatives)
- Si aucun plugin trouve : creer un fichier vide `{"scan_date": "...", "plugins": []}` et loguer "Aucun nouveau plugin"
- Si le catalogue est inaccessible : arreter et loguer l'erreur sans modifier de fichiers
