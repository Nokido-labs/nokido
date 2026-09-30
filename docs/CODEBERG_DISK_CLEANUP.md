# Codeberg disk warning — plan de cleanup

## Diagnostic

`git count-objects -vH` du repo Nokido :
- **size-pack = 477.80 MiB** (historique git)
- 1328 objets loose + 4 packs

Top 20 blobs > 100 KiB dans l'historique (déjà gitignored mais commités avant) :

| Taille | Blob |
|---|---|
| 49 MB | sandbox/benchmarks/gnn_data/CiteSeer/processed/data.pt |
| 41 MB | sandbox/benchmarks/gnn_data/PubMed/processed/data.pt |
| 34 MB | sandbox/benchmarks/attack_enterprise.json |
| 33 MB | data/replica.db |
| 18 MB | sandbox/benchmarks/beir_data/fiqa.zip |
| 16 MB | sandbox/benchmarks/gnn_data/Cora/processed/data.pt |
| 15 MB | sandbox/longmemeval/longmemeval_oracle.json |
| 11 MB | sandbox/ctf_challenges/darkunion1/handout.tar.gz |
| 10 MB | llama-api-server.wasm |
| 10 MB | sandbox/ctf_challenges/triathlon_or_sprint/challenge.tar |
| 9 MB | sandbox/ch33_real/android-sources/*.apk |
| 9 MB | sandbox/ctf_challenges/darkunion1/bzImage |
| 8 MB | sandbox/ctf_challenges/philanthropy/ch.tar |

Total purgeable : **~300 MB** de blobs binaires (benchmarks datasets PyTorch + CTF tarballs + WASM + APK).

## Solutions (3 niveaux)

### Niveau 1 : `git rm --cached` (gain NUL sur disque, juste anti-futur-commit)
Déjà gitignored — pas de gain. **Skip**.

### Niveau 2 : passer le repo PUBLIC AGPLv3 (gain politique, pas disque)
Codeberg accepte plus de space sur repos publics. Mais decision user = pas-de-suite (cf [[roadmap-product-nokido]] Phase 3).

### Niveau 3 : `git-filter-repo` rewrite history (vrai gain ~300 MB)

**Destructif** : réécrit tous les SHAs commit. Tous les remotes doivent être force-pushed. Backups recommandés.

#### Procedure

```bash
# 1. Backup (clone full hors-place)
cd /tmp
git clone --mirror https://github.com/user/Nokido.git Nokido-backup.git

# 2. Installer git-filter-repo
pip install git-filter-repo
# ou : apt install git-filter-repo (Debian)

# 3. Cloner fresh + purge
cd /tmp
git clone https://github.com/user/Nokido.git Nokido-clean
cd Nokido-clean

# 4. Purge les chemins lourds (modifier liste si besoin)
git filter-repo \
  --path sandbox/benchmarks/gnn_data \
  --path sandbox/benchmarks/beir_data \
  --path sandbox/benchmarks/ogb_data \
  --path sandbox/benchmarks/attack_enterprise.json \
  --path sandbox/longmemeval \
  --path sandbox/ctf_challenges \
  --path sandbox/ch33_real \
  --path data/replica.db \
  --path llama-api-server.wasm \
  --path app/forge_agents.c \
  --invert-paths

# 5. Verifier nouveau size
git count-objects -vH
# Attendu : size-pack < 200 MB

# 6. Force-push GitHub (destructif, prevenir collaborateurs)
git remote add github https://github.com/user/Nokido.git
git push --force --all github
git push --force --tags github

# 7. Force-push Codeberg (idem)
git remote add codeberg https://codeberg.org/user/Nokido.git
git push --force --all codeberg
git push --force --tags codeberg

# 8. (optionnel) garbage collect cote serveur
# GitHub : Settings > "Run garbage collection" (rare)
# Codeberg : ouvrir ticket support, ils gc periodiquement
```

#### Risques

- **Force-push** = tout collaborateur a un repo invalide, doit re-cloner
- **SHA changes** = tous les liens commit (`https://github.com/.../commit/<sha>`) sont morts
- **CI runs historiques** = orphelins dans GitHub Actions UI
- **Issue/PR comments** referencant commits = links morts

#### Alternative shallow re-push (moins destructif)

Crée un repo Codeberg neuf, push depuis un clone shallow :

```bash
cd /tmp
git clone --depth 1 https://github.com/user/Nokido.git Nokido-shallow
cd Nokido-shallow

# Add remote new + push fresh
git remote add codeberg-slim https://codeberg.org/user/Nokido-slim.git
git push --all codeberg-slim

# Puis archive l ancien repo Codeberg + rename slim -> Nokido
```

Inconvenient : perd tout l historique sur Codeberg (mais GitHub garde tout).

## Recommandation

1. **Court terme** : ignore le warning Codeberg (.gitignore actuel empeche futur grow)
2. **Moyen terme** : execute git-filter-repo + force-push **APRES** decision user (destructif)
3. **Long terme** : passer repo public AGPLv3 = Codeberg accepte le size

## Verifications post-cleanup

```bash
# Apres filter-repo + push, sur clone fresh :
git count-objects -vH | grep size-pack
# Doit afficher < 200 MB

# Verifier qu aucun gros blob ne reste
git rev-list --objects --all | \
  git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' | \
  awk '$2 > 1000000' | sort -rn | head -10
```
