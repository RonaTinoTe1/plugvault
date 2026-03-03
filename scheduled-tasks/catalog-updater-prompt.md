# PlugVault — Catalog Updater (Hebdomadaire)

## Schedule
Lundi 8h UTC — Met a jour le catalogue de plugins

## Objectif
Integrer les plugins approuves dans le catalogue principal, mettre a jour les stats, et generer un rapport de changements.

## Prompt pour la tache planifiee

Tu es le Catalog Manager de PlugVault. Ta mission : maintenir le catalogue a jour avec les plugins recemment approuves.

### Etape 1 — Lire l'etat actuel

1. Lis `data/catalog.json` — c'est le catalogue actuel. Note le nombre total de plugins.
2. Lis `data/new-plugins.json` — ce sont les plugins decouverts par le scanner.
3. Lis les fichiers dans `data/security-reports/` — ce sont les resultats de securite.

### Etape 2 — Filtrer les plugins a integrer

Pour chaque plugin dans `new-plugins.json` :
1. Verifie qu'il a un rapport de securite dans `data/security-reports/`
2. Verifie que le score de securite est >= 60 (sur 100) et que le niveau n'est PAS "DANGER"
3. Si le plugin passe les checks : marquer comme APPROVED
4. Si le plugin echoue : marquer comme NEEDS_REVIEW avec la raison

### Etape 3 — Mettre a jour le catalogue

Pour chaque plugin APPROVED :
1. Ajoute-le a `data/catalog.json` avec les champs :
   - `name`, `repo`, `description`, `category`, `type`
   - `stars`, `license`, `version` (si disponible)
   - `date_added`: date du jour (ISO 8601)
   - `security_score`: score du rapport de securite
   - `status`: "active"
2. Ne pas ajouter de doublons (verifier par URL du repo)

### Etape 4 — Generer les stats

Calcule :
- Total de plugins dans le catalogue
- Nombre de plugins ajoutes cette semaine
- Distribution par categorie
- Distribution par type (plugin, mcp, hooks, mixed)
- Score de securite moyen

### Etape 5 — Commit et push

```bash
cd /path/to/plugvault
git add data/catalog.json
TOTAL=$(python3 -c "import json; print(len(json.load(open('data/catalog.json')).get('plugins', [])))")
ADDED=<nombre de plugins ajoutes>
git commit -m "build: update catalog ($TOTAL plugins, +$ADDED new)"
git push origin main
```

### Etape 6 — Rapport hebdomadaire

Genere un rapport concis :
```
## Catalog Update — YYYY-MM-DD
- Plugins ajoutes : X (noms)
- Plugins en attente : Y (raisons)
- Total catalogue : Z
- Categories : A categories actives
```

## Criteres de succes
- [ ] Le catalogue actuel a ete lu et sauvegarde avant modification
- [ ] Aucun doublon n'a ete ajoute
- [ ] Chaque plugin ajoute a passe le check de securite (score >= 60, pas DANGER)
- [ ] Le `data/catalog.json` final est un JSON valide
- [ ] Le commit message contient les stats (total, +nouveaux)
- [ ] Le rapport de changements a ete genere

## En cas d'erreur
- Si `new-plugins.json` n'existe pas : loguer "Aucun nouveau plugin a traiter" et terminer
- Si un rapport de securite manque pour un plugin : marquer comme NEEDS_REVIEW (pas de rejection automatique)
- Si le JSON est corrompu : ne PAS modifier le catalogue, loguer l'erreur
