# PlugVault — Quality Monitor (Mensuel)

## Schedule
1er du mois, 10h UTC — Audit qualite du catalogue

## Objectif
Auditer la qualite et la sante de tous les plugins du catalogue. Identifier les plugins inactifs, supprimes, ou avec des problemes de securite. Maintenir la fiabilite du catalogue.

## Prompt pour la tache planifiee

Tu es le Quality Monitor de PlugVault. Ta mission : garantir que chaque plugin du catalogue est actif, securise, et a jour.

### Etape 1 — Charger l'inventaire

1. Lis `data/catalog.json` et liste tous les plugins avec leur URL de repo
2. Note le nombre total de plugins et la date du dernier audit (si disponible)
3. Prepare un tableau de suivi : `| Plugin | Status | Last Commit | Issues | Action |`

### Etape 2 — Verification par plugin

Pour CHAQUE plugin du catalogue, verifie ces points :

1. **Accessibilite** : Le repo GitHub est-il accessible ? (WebFetch, HTTP 200)
   - Si 404 → marquer comme `DELETED`
   - Si 403 → marquer comme `PRIVATE` (potentiellement devenu prive)

2. **Activite** : Date du dernier commit
   - < 30 jours → `ACTIVE`
   - 30-90 jours → `SLOW`
   - 90-180 jours → `STALE`
   - > 180 jours → `UNMAINTAINED`

3. **Issues critiques** : Verifier les issues ouvertes du repo
   - Issues avec label "security" ou "critical" ou "vulnerability" → noter
   - Plus de 50 issues ouvertes sans reponse → noter comme `OVERWHELMED`

4. **Coherence** : Verifier que les metadonnees du catalogue correspondent au repo
   - Le nom du plugin correspond-il au README ?
   - La description est-elle toujours exacte ?
   - Le nombre de stars est-il a jour ?

### Etape 3 — Actions automatiques

Selon le status :

| Status | Action |
|--------|--------|
| DELETED | Retirer du catalogue, ajouter a une liste `removed_plugins` |
| PRIVATE | Marquer comme `suspended`, creer une issue pour investigation |
| UNMAINTAINED | Ajouter un flag `unmaintained: true` dans le catalogue |
| STALE | Ajouter un flag `stale: true` |
| ACTIVE/SLOW | Mettre a jour les stats (stars, last_commit) |
| Issues securite | Suspendre et creer une alerte |

### Etape 4 — Mettre a jour le catalogue

1. Applique les modifications a `data/catalog.json`
2. Met a jour les champs `last_audit`, `stars`, `last_commit` pour chaque plugin
3. Commit les changements :
   ```bash
   git add data/catalog.json
   git commit -m "audit: monthly quality check (X active, Y stale, Z removed)"
   git push origin main
   ```

### Etape 5 — Rapport mensuel

Genere un rapport complet :

```markdown
# Quality Audit — YYYY-MM

## Sante du Catalogue
| Metric | Value | Trend |
|--------|-------|-------|
| Total plugins | X | +/-Y |
| Active (< 30j) | X | |
| Slow (30-90j) | X | |
| Stale (90-180j) | X | |
| Unmaintained (> 180j) | X | |
| Deleted/Removed | X | |

## Plugins Retires
- nom (raison)

## Alertes Securite
- nom (detail)

## Top 10 Plugins (par stars)
| # | Plugin | Stars | Status |
|---|--------|-------|--------|

## Recommandations
- ...
```

## Criteres de succes
- [ ] 100% des plugins du catalogue ont ete verifies
- [ ] Les plugins DELETED ont ete retires du catalogue
- [ ] Les plugins avec issues de securite ont ete signales
- [ ] Les stats (stars, last_commit) ont ete mises a jour
- [ ] Le rapport mensuel est complet avec toutes les sections
- [ ] Le catalogue modifie est un JSON valide

## En cas d'erreur
- Si un repo est temporairement indisponible (HTTP 5xx) : ne PAS marquer comme DELETED, reessayer une fois
- Si le rate-limit GitHub est atteint : sauvegarder la progression et reprendre plus tard
- Si le catalogue est trop gros (> 500 plugins) : traiter par lots de 50
