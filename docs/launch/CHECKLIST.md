# ✅ Launch CHECKLIST — copy-paste commands

## J-1 (la veille — ce soir)

### Hardening visibilité

```bash
# Vérifier que la branche par défaut sur le repo privé est bien beta (pas alpha)
gh repo edit user/Nokido --default-branch beta

# Vérifier qu'aucun token reste tracké (audit final)
C:/tmp/gitleaks_dl/gitleaks.exe detect \
  --source "~/Script python IA/Nokido" \
  --config "~/Script python IA/Nokido/.gitleaks.toml" \
  --no-banner
# Attendu: no leaks found

# Push final si modifs en attente
cd "~/Script python IA/Nokido"
git status
git push origin alpha
git checkout beta && git merge --ff-only alpha && git push origin beta && git checkout alpha
```

### Enregistrer les médias

1. **Terminal demo** (asciinema) — voir [asciinema_script.md](asciinema_script.md)
2. **Web UI demo** (ScreenToGif ou Xbox Game Bar) — voir [screencast_alternatives.md](screencast_alternatives.md)

Garde :
- 1 × GIF court (8-12s, < 2 MB) pour Twitter
- 1 × MP4/cast long (45-60s) pour HN/Reddit/YouTube

### Préparer comptes sociaux

- [ ] **GitHub** — repo `user/Nokido` (privé pour toujours) ; mirror public à venir `user/Nokido-public`
- [ ] **X/Twitter** — handle créé, bio :
  > Building Nokido — Autonomous local-first AI OS with neuro-symbolic governance. AGPLv3. Solo dev.
- [ ] **Hacker News** — account créé, karma ≥ 0 OK
- [ ] **Reddit** — account avec ≥100 karma (sinon r/LocalLLaMA filtre)
- [ ] **Lobste.rs** — account créé (invite-only, demander à un ami si pas déjà)
- [ ] **BlueSky** (optionnel) — handle créé
- [ ] **Mastodon fosstodon.org** (optionnel)

## J-0 — Mercredi 14h00 Paris (stratégie : mirror clean-slate `Nokido-public`)

### Orchestrateur unique : `tools/launch_public_mirror.py`

Le repo privé `user/Nokido` reste privé pour toujours. On crée un **nouveau** dépôt public `user/Nokido-public` à partir d'un **single commit propre** signé `user <user@users.noreply.github.com>`. Tout l'historique alpha (avec ses ~8 fuites historiques de tokens depuis migrés au vault) reste hors-ligne.

```bash
# Phase 1 (14h00) — Générer le ZIP eSoleau
LAFORGE_PYTHON tools/launch_public_mirror.py --esoleau-zip
# → C:/tmp/laforge-v0.1.0-rc.zip + SHA-256 affiché
# → Note le SHA-256 quelque part.

# Phase 1.5 (14h00-14h15) — Upload eSoleau manuel (15 €)
# https://www.inpi.fr/fr/services-en-ligne/depot-de-creation-en-ligne-e-soleau
# Sauvegarde le PDF reçu dans ~/Documents/LaForge-Legal/

# Phase 2 (14h15) — Clean-slate staging (NO push)
LAFORGE_PYTHON tools/launch_public_mirror.py --prepare
# → C:/tmp/laforge-public-staging/ avec single commit signé v0.1.0

# Phase 3 (14h20) — Créer le repo public sur GitHub (VIDE, pas encore poussé)
LAFORGE_PYTHON tools/launch_public_mirror.py --create-remote
# → user/Nokido-public créé, description + topics appliqués
```

### Pre-flight final (14h22)

```bash
cd "~/Script python IA/Nokido"

# Hub up + healthy
curl http://localhost:8766/health

# Tous tests passent
git -C "." log --oneline -3
gh run list -R user/Nokido --branch beta --limit 3
# Tous "success"

# Wiki présent en local
ls docs/wiki/*.md | wc -l
# Attendu: ~36 (18 EN + 18 FR)

# README traductions
ls README*.md
# Attendu: 8 (en, fr, es, zh-CN, pt-BR, ja, de, ar)
```

### Push public (14h25 — 5 min avant launch posts)

⚠️ **ACTION IRRÉVERSIBLE** — le commit signé apparaîtra sur GitHub public dès cette commande. Ne pas exécuter sans le PDF eSoleau en main.

```bash
# DERNIER MOMENT pour annuler
# Confirmer que tout est prêt :
#   ✅ ZIP eSoleau uploadé + PDF reçu sauvegardé
#   ✅ SSH signing key configurée (git config --global gpg.format ssh)
#   ✅ Pre-flight checklist au-dessus toute verte

# PUSH PUBLIC (requiert le flag explicite)
LAFORGE_PYTHON tools/launch_public_mirror.py --push --i-have-esoleau-receipt

# Branch protection (~30 sec après le push)
LAFORGE_PYTHON tools/launch_public_mirror.py --protect-main

# Vérifier
gh repo view user/Nokido-public --json visibility,defaultBranchRef
# Attendu: {"visibility":"PUBLIC","defaultBranchRef":{"name":"main"}}
```

### Garde-fou : si quelque chose part de travers

Si tu détectes un problème dans la première minute (commit non signé, fichier sensible passé, mauvaise description) :

```bash
# Bascule en privé (réversible tant que personne n'a forké)
gh repo edit user/Nokido-public --visibility private

# Ou nuke complet (~30 sec, irréversible)
gh repo delete user/Nokido-public --yes

# Refaire : --prepare + corriger + --push
```

### Posts coordonnés (14h30)

Ordre de submission rapide :

1. **Tweet thread X** (14h30 sharp)
   - Copier depuis [tweet_thread.md](tweet_thread.md)
   - Joindre GIF demo au premier tweet
   - Programmer les 9 suivants ou poster manuellement à 30s d'intervalle

2. **Show HN** (14h32)
   - Titre + URL repo + body depuis [show_hn.md](show_hn.md)
   - URL : https://github.com/user/Nokido-public

3. **r/LocalLLaMA** (14h35)
   - Body natif depuis [reddit_localllama.md](reddit_localllama.md)
   - **Pas un copier-coller du tweet** — texte différent
   - Image GIF en pièce jointe

4. **r/selfhosted** (14h45)
   - Body depuis [reddit_selfhosted.md](reddit_selfhosted.md)

5. **r/ClaudeAI + r/Anthropic** (14h50)
   - Body depuis [reddit_anthropic.md](reddit_anthropic.md)

6. **Lobste.rs** (15h00)
   - URL repo + tags `ai`, `python`, `rust`, `practices`
   - Voir [lobsters.md](lobsters.md)

7. **PRs awesome-lists** (15h15)
   - PR awesome-mcp + awesome-ai-agents + awesome-selfhosted
   - Voir [awesome_lists.md](awesome_lists.md)

8. **Mentions X ciblées** (15h30)
   - Tweet de réponse à 1-2 comptes pertinents : Karpathy, LeCun, Friston (sans bot-spam, 1 mention max)
   - Cite l'aspect qui les concerne (active inference, sovereignty, neuro-symbolic)

## J+1 (Jeudi)

### Suivi 24h après

- [ ] Répondre à TOUS les commentaires HN (priorité absolue)
- [ ] Répondre à TOUS les commentaires Reddit
- [ ] Vérifier issues GitHub ouvertes (target : <2h response time)
- [ ] Suivre les stars (peut tracker via `gh repo view user/Nokido-public --json stargazerCount`)
- [ ] Monitorer logs hub si tu as activé Sentry/équivalent
- [ ] Voir [followup_24h.md](followup_24h.md) pour réponses prêtes aux questions communes

### Itération rapide

Si bug critique trouvé par un early adopter :

```bash
# Fix sur alpha
git checkout alpha
# ... edit ...
git commit -m "fix(critical): <description>"
git push origin alpha

# Forward to beta
git checkout beta && git merge --ff-only alpha && git push origin beta && git checkout alpha
```

Tu peux faire des releases hot-fix sans drame — les vrais utilisateurs apprécient la réactivité.

## 🆘 Si ça part mal

### Bug critique non-anticipé apparait

1. Reconnaître publiquement (tweet + commentaire HN/Reddit) — pas cacher.
2. Si exploit security : `gh repo edit user/Nokido-public --visibility private` immédiatement, fix, re-public 1h plus tard avec mea culpa.
3. Si "ça plante chez moi" générique : guider vers `docs/wiki/14-Troubleshooting.md`, demander logs.

### Front-page HN mais ça froidit ensuite

Normal. La courbe HN dure 24-48h. Continue de répondre aux comments.

### 0 traction

Normal aussi (60% des Show HN ne décollent pas). Pas de honte. Garde le repo public, continue les commits, retente dans 3-6 mois avec une feature majeure.

### Compte X verrouillé pour "spam"

Ne pas tweeter en rafale > 5 tweets/heure les premières semaines. Si verrouillé, attendre 24h.

## 📊 Métriques succès (24h post-launch)

| Métrique | Mauvais | OK | Bon | Excellent |
|---|---|---|---|---|
| GitHub stars | <30 | 30-100 | 100-500 | 500+ |
| HN points | <20 | 20-100 | 100-300 | 300+ |
| r/LocalLLaMA upvotes | <50 | 50-200 | 200-500 | 500+ |
| Issues ouvertes | 0 | 1-5 | 5-15 | 15+ |
| Forks | 0 | 1-5 | 5-20 | 20+ |
| Reach Twitter (impressions) | <500 | 500-5k | 5k-50k | 50k+ |

Cible réaliste pour un Show HN bien structuré : **100-300 stars** en 24h.
