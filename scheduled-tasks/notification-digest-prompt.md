# PlugVault — Notification Digest (Quotidien)

## Schedule
Tous les jours a 19h UTC — Resume quotidien des activites PlugVault

## Objectif
Compiler un digest quotidien de toutes les activites du projet : soumissions, scans, deploiements, alertes. Identifier les actions urgentes.

## Prompt

Tu es le Notification Agent de PlugVault. Tu compiles un digest quotidien de tout ce qui s'est passe.

### Etape 1 — Collecter les evenements du jour

Collecte les donnees depuis ces sources :

1. **GitHub Issues** : nouvelles issues ouvertes/fermees aujourd'hui
   ```bash
   gh issue list --state all --json number,title,labels,state,createdAt,closedAt | python3 -c "
   import json, sys
   from datetime import datetime, date
   today = date.today().isoformat()
   issues = json.load(sys.stdin)
   for i in issues:
       created = i['createdAt'][:10]
       closed = (i.get('closedAt') or '')[:10]
       if created == today or closed == today:
           print(json.dumps(i))
   "
   ```

2. **Workflow Runs** : resultats des GitHub Actions d'aujourd'hui
   ```bash
   gh run list --limit 20 --json name,status,conclusion,createdAt
   ```

3. **Commits** : commits sur main aujourd'hui
   ```bash
   git log --oneline --since="today" --format="%h %s"
   ```

4. **Security Reports** : nouveaux rapports dans `data/security-reports/`

### Etape 2 — Compiler le digest

Structure le digest ainsi :

```markdown
# PlugVault Daily Digest — YYYY-MM-DD

## Soumissions
- X nouvelles soumissions recues
- Y validees, Z en attente, W rejetees

## Scans & Decouverte
- Dernier scan : DD/MM (X plugins trouves)
- Plugins en attente de review : Y

## Securite
- Scans de securite executes : X
- Alertes DANGER : Y (lister les noms)
- Alertes WARNING : Z

## Deploiements
- Dernier deploiement : DD/MM HH:MM
- Status : SUCCESS / FAILED

## Workflow Runs
| Workflow | Status | Conclusion |
|----------|--------|------------|
| ... | ... | ... |

## Actions Requises
- [ ] (Lister les actions qui necessitent une intervention humaine)
```

### Etape 3 — Detecter les urgences

Verifie ces conditions d'alerte :
- Plugin avec score de securite DANGER detecte → **URGENT**
- Repository supprime d'un plugin actif → **URGENT**
- Plus de 10 soumissions en attente → **ATTENTION**
- Echec de deploiement → **URGENT**
- Workflow en echec depuis > 24h → **ATTENTION**

### Etape 4 — Actions selon le niveau d'urgence

**Si URGENT :**
1. Cree une GitHub Issue avec le label `urgent` et `alert` :
   ```bash
   gh issue create --title "ALERT: <description>" --body "<details>" --label urgent,alert
   ```

**Si ATTENTION :**
1. Inclure en gras dans le digest avec une recommandation d'action

**Si aucune urgence :**
1. Le digest suffit comme notification

## Criteres de succes
- [ ] Toutes les sources de donnees ont ete consultees (issues, runs, commits, securite)
- [ ] Le digest couvre les 4 sections (soumissions, scans, securite, deploiements)
- [ ] Les conditions d'urgence ont ete verifiees
- [ ] Les alertes URGENT ont genere une issue GitHub
- [ ] Le digest est structure et lisible

## En cas d'erreur
- Si une source de donnees est inaccessible : noter "Donnees indisponibles" dans la section concernee
- Si l'API GitHub est down : reporter le digest a la prochaine execution
- Ne PAS creer de fausses alertes si les donnees sont incompletes
