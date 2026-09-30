# 🚀 Nokido — Launch kit

Tout le matériel pour le lancement public coordonné. Date cible : **mercredi
14h30-15h30 Paris** (= 08h30-09h30 EST, golden window front-page HN).

## 📂 Contenu

| Fichier | Rôle |
|---|---|
| [CHECKLIST.md](CHECKLIST.md) | Liste exhaustive J-1 / J-0 / J+1 avec commandes prêtes à copier |
| [asciinema_script.md](asciinema_script.md) | Script terminal pour démo TUI + hub + first call |
| [screencast_alternatives.md](screencast_alternatives.md) | ScreenToGif + Xbox Game Bar (sans OBS) pour UI web |
| [tweet_thread.md](tweet_thread.md) | Thread X/Twitter 10 tweets + variations |
| [show_hn.md](show_hn.md) | Titre + body Show HN |
| [reddit_localllama.md](reddit_localllama.md) | Post r/LocalLLaMA |
| [reddit_selfhosted.md](reddit_selfhosted.md) | Post r/selfhosted |
| [reddit_anthropic.md](reddit_anthropic.md) | Cross-post r/ClaudeAI + r/Anthropic |
| [lobsters.md](lobsters.md) | Soumission Lobste.rs |
| [awesome_lists.md](awesome_lists.md) | PR templates pour awesome-mcp, awesome-ai-agents, awesome-selfhosted |
| [followup_24h.md](followup_24h.md) | Réponses prêtes aux questions communes |

## 🕒 Timing exact

| Heure Paris | Action |
|---|---|
| **14:00** | Final pre-flight check : `bash docs/launch/preflight.sh` |
| **14:15** | Enregistrer le GIF demo (TUI + admin UI) si pas fait |
| **14:25** | Flip visibility public + flip default branch beta |
| **14:30** | Tweet thread part 1 (hook + GIF) |
| **14:32** | Post Show HN |
| **14:35** | Post r/LocalLLaMA |
| **14:45** | Cross-post r/selfhosted + r/ClaudeAI |
| **15:00** | Soumettre Lobste.rs |
| **15:15** | Ouvrir PRs awesome-mcp + awesome-ai-agents |
| **15:30** | Mention quelques comptes X tech (LeCun, Karpathy, awesome-list maintainers) |

## ✅ État pré-launch (à vérifier avant)

- [ ] README.md restructuré + 7 traductions présentes
- [ ] MANIFESTO.md présent
- [ ] SECURITY.md + CODE_OF_CONDUCT.md + CONTRIBUTING.md présents
- [ ] Wiki 18 pages × EN + FR présent
- [ ] CI 5/5 jobs vert (Ubuntu + macOS + Windows)
- [ ] Gitleaks baseline 177 fingerprints
- [ ] Provider admin UI fonctionnelle `/admin/providers`
- [ ] Pre-commit hook secrets actif
- [ ] Vault peuplé 14/14 tokens
- [ ] Docker `core` profile up-and-running localement
- [ ] Demo GIF prêt (TUI + UI web)
- [ ] Show HN account créé (account âge ≥ 1 an préféré, sinon laisser passer 1h après création)
- [ ] X account créé + bio + photo
- [ ] Reddit account avec karma ≥ 100 (pinche r/LocalLLaMA — accounts neufs filtrés)

## 📞 Bouton ROUGE — si ça part mal

Annuler le launch :
```bash
gh repo edit user/Nokido --visibility private
```

Tweet/post deletion : tout supprimer manuellement. Repo redevient privé instantanément.

Memory `public_release_audit_2026-05-26` valide la stratégie miroir si on veut clean-slate v0.1.0 plus tard.
