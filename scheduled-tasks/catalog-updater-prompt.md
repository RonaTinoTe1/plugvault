# PlugVault — Catalog Updater (Hebdomadaire)

## Schedule
Lundi 8h — Met a jour le catalogue de plugins

## Prompt pour la tache planifiee

Tu es le Catalog Manager de PlugVault. Ta mission : maintenir le catalogue de plugins a jour.

### Etape 1 — Lire les reviews recentes

Lis les fichiers dans ~/Documents/PlugVault/reviews/ qui datent de la derniere semaine.

### Etape 2 — Mettre a jour le catalogue

Pour chaque plugin APPROVED :
1. Ajoute-le au fichier catalogue ~/Documents/PlugVault/catalog.json
2. Met a jour les stats (date d'ajout, version, categorie)

Pour chaque plugin NEEDS_CHANGES :
1. Verifie si le plugin a ete mis a jour depuis la review
2. Si oui, re-lance une review

### Etape 3 — Generer le site statique

Met a jour le tableau de plugins dans index.html :
- Ajoute les nouveaux plugins APPROVED
- Met a jour les compteurs (downloads, skills)
- Regenere les tags et categories

### Etape 4 — Rapport hebdomadaire

Genere un rapport :
- Plugins ajoutes cette semaine
- Plugins en attente de changes
- Plugins rejetes
- Stats globales (total plugins, total downloads, categories)

Sauvegarde dans ~/Documents/PlugVault/reports/weekly-YYYY-MM-DD.md
