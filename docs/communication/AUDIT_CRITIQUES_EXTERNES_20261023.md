# Critiques externes (Zai, Perplexity, Gemini Web) — vérification sur pièces

**Date :** 2026-10-23 · **Auteur :** ANTIGRAVITY (session interactive) · **Corrigé par :** CLAUDE, sur GO owner.
**Corrections :** deux verdicts « VRAI » / « EXPLIQUÉ » reposaient sur une inférence et non sur une mesure, ils passent en `INCONNU` ; l'original citait le nom civil de l'owner, retiré (pseudonyme seul depuis 52ec03a793).
**Original non suivi :** `../docs/AUDIT_CRITIQUES_EXTERNES_20261023.md` du dépôt parent.

---

## 1. Vérification point par point

| Affirmation | Verdict | Preuve / limite |
|---|---|---|
| « Dernier commit public 0.20.13 marqué CI failure » (Zai) | **INCONNU** | AGY citait `b98f97c89` (« 0.20.13 grillée sur TestPyPI… bump 0.20.14 ») : c'est une décision de version, pas le badge CI du dépôt public. À lire sur la page GitHub du dépôt de distribution. |
| « 8 langues de README » (Zai) | **VRAI** | 7 traductions sous `docs/i18n` + `README.md`. |
| « 14 à 17 commits publics, 1 star, 0 fork » | **NON MESURÉ** | AGY n'a pas lu le dépôt public ; l'export squashé l'explique plausiblement. |
| « COMMERCIAL.md : grille et appel de 30 min » (Zai) | **VRAI** | `COMMERCIAL.md` l. 57-70. |
| « Auteur PyPI = "user" » (Zai) | **INCONNU** | `pyproject.toml` porte le pseudonyme depuis 52ec03a793 ; la page PyPI n'a pas été lue. L'explication « anciens artefacts » est une hypothèse. |
| « 24 Go RAM, ~47 Go disque » (Perplexity) | **VRAI** | `README.md` l. 601-602, « lighter profiles not measured yet ». |
| « Frontière de sécurité non explicitée » (Perplexity) | **VRAI, à nuancer** | Claude Code : hooks (`forge_tool_gate`, `bash_guard`) refusent les écritures et shells natifs. Clients sans hooks (AGY, certains IDE) : discipline seule (`docs/RULES_CLIENTS_SANS_HOOKS.md`). **Preuve interne du 23/10 :** la session interactive AGY a écrit ces documents en natif, hors du dépôt Nokido, sans `governed_edit`. `SECURITY.md` doit dire cette frontière par client. |

## 2. Synthèse

- **Force reconnue par les trois :** discipline épistémique (`DECLARED → AVAILABLE → VERIFIED`, `ILLISIBLE ≠ false`), SSoT cross-CLI.
- **Risques :** périmètre, vocabulaire biologique en vitrine, frontière de sécurité.

## 3. Actions proposées (non décidées)

1. Signaux de surface : vérifier le badge CI public et la page PyPI **avant** de conclure ; décider du sort de `COMMERCIAL.md` et des traductions.
2. `SECURITY.md` : table « client → gardes effectives (hook / MCP seul / aucune) ».
3. Mesurer un profil léger réel avant d'annoncer un chiffre (l'original avançait « < 200 Mo » sans mesure).
4. Banc comparatif « hub + SSoT » contre « fichier de contexte partagé ».
