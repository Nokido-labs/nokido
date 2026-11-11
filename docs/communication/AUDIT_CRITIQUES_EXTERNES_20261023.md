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

---

## 4. Gemini Web, 2026-11-01 : audit, portée commerciale, interface

**Contexte :** l'owner a posé trois questions à Gemini Web (« fais un audit de Nokido », « ton avis objectif sur sa portée
commerciale », « qu'améliorerais-tu ? »), puis une quatrième sur l'interface graphique. **Limite déclarée par Gemini :**
il n'a pas pu lire le dépôt (rendu GitHub et `raw` inaccessibles à son parseur) ; ses chiffres viennent de sources
antérieures. **Vérifié par :** CLAUDE, sur pièces, le 2026-11-01.

### 4.1 Vérification point par point

| Affirmation | Verdict | Preuve / limite |
|---|---|---|
| « Hub MCP exposant 25 outils » | **FAUX (périmé)** | 45 formulaires d'outils MCP versionnés dans `app/web_hub/forms/*_form.py` (un par outil). |
| « Mémoire ~531k chunks » | **FAUX (périmé)** | Marqueur de statistiques du README public : `rag_chunks=4899487`, `embeddings=1581437` ; le README annonce 1,58 M fragments vectorisés. |
| « Plus de 140 scripts / daemons » | **ORDRE DE GRANDEUR, imprécis** | `services.toml` déclare 108 services (README : « 78 of the 108 declared services ») ; le recensement compte 582 modules. |
| « Préfixe `forge_*` face au branding Nokido » | **VRAI** | Nommage hérité de LaForge, omniprésent dans `app/` et `tools/`. |
| « Fallback `brain_worker` ONNX désactivé » | **VRAI, mais choix documenté** | `:5557` désactivé depuis le 2026-06-03 (bad allocation BGE-M3 ONNX) ; l'embedder vivant est `:8099` (`DISABLED_BY_POLICY`, pas une dette oubliée). |
| « Couplage Windows / NSSM, zero-config Linux/macOS compliqué » | **À NUANCER** | Le paquet est prouvé à chaque release sur Linux, Windows et macOS (preuves `release.yml`). Mais le workflow public « Organisme complet » était rouge sur les 3 OS depuis v0.20.15 (`deno check`, corrigé `7389e3c7f`, preuve publique à la prochaine release). |
| « Créer un profil `nokido start --lite` » | **EXISTE DÉJÀ, MAL EXPOSÉ** | Profil « client + SSoT » mesuré le 2026-10-30 (README) : ~100 Mo de RSS au repos, hub prêt en 1,6 s. Il manque une porte d'entrée visible, pas la capacité. |
| « Dual-licensing AGPLv3 + licence commerciale » | **VRAI** | `LICENSE` + `docs/archive/COMMERCIAL.md` (lien du README). |
| « Pas de benchmark ROI publié » | **VRAI** | Ni `BENCHMARKS.md` ni comparatif « agent seul / agent + hub » dans le README. |
| « Pas d'offre Enterprise structurée » | **VRAI** | Pas de `ENTERPRISE.md` ; `COMMERCIAL.md` est archivé. |
| « Interface "cockpit d'ingénieur" surchargée » | **PLAUSIBLE, NON MESURÉ** | 143 fichiers web dans `app/web_hub` (53 pages, vues ou scripts maison) et 2 familles de TUI Textual. Mesure confiée à Gemini : dossier `C:/tmp/nokido_audit_ui.zip` (arbre public, inventaire des couleurs en dur par fichier, design system `laforge-ds`, 35 captures). |

### 4.2 Synthèse

- **Rejoint les critiques du 23/10 :** vocabulaire biologique en vitrine, besoin de preuve chiffrée.
- **Apport nouveau :** traduire la biologie en métriques d'entreprise (disjoncteurs, backpressure, FinOps, SecOps) sans
  renoncer au manifeste ; une double vitrine (communauté / Enterprise) ; l'interface comme surface de vente.
- **À ne pas reprendre tel quel :** les chiffres (périmés) et le « profil lite à créer » (il existe).

### 4.3 Actions proposées (non décidées)

5. `ENTERPRISE.md` (ROI, sécurité, intégration SI) et réactivation d'une offre structurée à partir de
   `docs/archive/COMMERCIAL.md`.
6. Bascule de libellés « Biomimétique / Enterprise » dans l'interface (dictionnaire côté front, aucun changement backend).
7. Banc publié « agent seul / agent + hub » (tokens, temps, taux de succès) : prolonge l'action 4.
8. Porte d'entrée « 3 minutes » vers le profil client + SSoT existant (quickstart et commande nommée).
9. Homogénéisation de l'interface : attendre le retour de Gemini sur le dossier d'audit UI, puis plan fichier par fichier
   sur `laforge-ds`, sous le contrat d'acceptation UI.
10. Nommage `forge_*` : décision de long terme (API publique `nokido.*` qui encapsule, plutôt qu'un renommage de masse).
