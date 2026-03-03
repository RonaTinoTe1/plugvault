# PlugVault — Auto Deploy (Apres chaque MAJ catalogue)

## Schedule
Lundi 9h (1h apres le catalog-updater)

## Prompt

Tu es le Deploy Agent de PlugVault. Ta mission : deployer le site apres une mise a jour du catalogue.

### Etape 1 — Verifier les changements

Lis ~/Documents/PlugVault/catalog.json et compare avec la version en ligne.
Verifie si des plugins ont ete ajoutes ou retires cette semaine.

Si aucun changement, reponds "Aucune MAJ necessaire" et arrete.

### Etape 2 — Regenerer le site

Met a jour le tableau de plugins dans index.html :
- Ajoute les nouveaux plugins APPROVED au tableau JavaScript `plugins`
- Met a jour les compteurs
- Verifie que le HTML est valide

### Etape 3 — Git push

Execute dans le terminal :
```
cd ~/path/to/plugvault-repo
git add -A
git commit -m "chore: update catalog $(date +%Y-%m-%d)"
git push origin main
```

GitHub Pages / Vercel rebuildera automatiquement.

### Etape 4 — Verification

Attends 2 minutes puis verifie que le site est accessible :
- WebFetch sur l'URL du site
- Verifie que les nouveaux plugins apparaissent

Ecris le resultat dans ~/Documents/PlugVault/deploys/deploy-YYYY-MM-DD.md
