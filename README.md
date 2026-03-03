# PlugVault — Claude Plugin Marketplace

Marketplace autonome de plugins pour Claude Code et Cowork.
Entierement gere par des agents IA et des taches planifiees.

---

## Architecture

```
Plugin-Marketplace/
|-- index.html                    # Site web (dark editorial)
|-- plugin-review-agent.py        # Agent autonome de review
|-- catalog.json                  # Catalogue des plugins (auto-genere)
|-- scheduled-tasks/
|   |-- plugin-scanner-prompt.md  # Dim 20h — Scan GitHub
|   |-- catalog-updater-prompt.md # Lun 8h — MAJ catalogue
|   |-- quality-monitor-prompt.md # 1er du mois — Audit qualite
|-- ~/Documents/PlugVault/
    |-- reviews/                  # Rapports de review
    |-- scans/                    # Resultats de scan
    |-- reports/                  # Rapports hebdo/mensuels
```

## Workflow autonome

1. **Scanner** (dimanche) — Recherche de nouveaux plugins sur GitHub
2. **Review Agent** (on-demand) — Analyse automatique des soumissions
3. **Catalog Updater** (lundi) — MAJ du site avec les plugins approuves
4. **Quality Monitor** (mensuel) — Audit et nettoyage du catalogue

## Usage

### Lancer une review manuelle
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python plugin-review-agent.py https://github.com/user/plugin
```

### Installer les taches planifiees
Dans Claude Cowork, creer 3 taches planifiees avec les prompts dans scheduled-tasks/.

## Stack

- **Frontend** : HTML/CSS/JS vanilla (dark editorial brutalist)
- **Backend** : Agents Python + Anthropic API
- **Automation** : Claude Cowork Scheduled Tasks
- **Hosting** : Statique (GitHub Pages, Vercel, ou local)

## Cout mensuel estime

| Composant | Frequence | Cout estime |
|-----------|-----------|-------------|
| Plugin Scanner | 1x/semaine | ~$0.10 |
| Review Agent | ~5x/semaine | ~$0.50 |
| Catalog Updater | 1x/semaine | ~$0.05 |
| Quality Monitor | 1x/mois | ~$0.10 |
| **Total** | | **~$3/mois** |

---

*PlugVault — Marketplace autonome, gere par agents IA.*
