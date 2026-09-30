# Design Doc — AIxCC-style Patch Assistant

**Status** : design figé, non implémenté.
**Scope** : outil défensif de remediation assistée.
**Auteur** : session 2026-04-19.
**Ce document n'est PAS une autorisation d'implémenter sans relecture.**
Quand tu seras prêt à coder, relis d'abord les sections "Ce qui est hors scope"
et "Tests d'acceptation qui doivent tous passer avant merge".

---

## 1. Intention

Aider un développeur à **remédier** des vulnérabilités déjà **détectées par
des linters de sécurité matures** dans son propre code source. L'outil ne
cherche pas de vulnérabilités à partir de rien — il prend les findings de
`bandit`, `semgrep`, `cppcheck`, et autres outils CI standards, puis propose
des patchs via LLM et les valide contre la suite de tests du projet.

Cas d'usage cibles :
- Ton propre code (projet perso, repo d'entreprise où tu es dev)
- Challenges DEF CON AIxCC officiels que tu as clonés depuis la sandbox
  fournie par l'organisation
- Exercices de type "patch generation" sur des repos volontairement
  vulnérables (OWASP WebGoat, Damn Vulnerable C Program, etc.)

Ce que l'outil n'est PAS :
- Un détecteur de vulnérabilités LLM-polyvalent
- Un scanner de code distant
- Un agent qui bouclerait sur n'importe quel code source pour y trouver
  des failles

---

## 2. Architecture

```
app/aixcc_agent/
├── __init__.py
├── config.py           Constantes, chemins, timeouts, limites
├── repo.py             Validation repo, clone temp, git status
├── detectors/
│   ├── __init__.py
│   ├── base.py         Interface DetectorAdapter
│   ├── bandit.py       Adapter subprocess -> bandit --format json
│   ├── semgrep.py      Adapter subprocess -> semgrep --json
│   └── cppcheck.py     Adapter subprocess -> cppcheck --output-format=xml
├── schema.py           Finding, Patch, TestResult dataclasses
├── llm_client.py       Wrapper autour de NokidoAgent existant
├── patcher.py          LLM prompt engineering -> patch diff + explanation
├── sandbox.py          Apply patch dans worktree git isolé, run tests
├── reporter.py         Markdown report + export vers DB ctf_reports
├── cli.py              Entrypoint : python -m app.aixcc_agent <repo>
└── README.md           Guide utilisateur final

tests/nr/test_aixcc_agent.py
```

---

## 3. Flux d'exécution

```
┌─────────────────────────────────────────────────────────────┐
│ 1. VALIDATION                                                │
│    - User fournit un chemin local de repo git               │
│    - repo.py vérifie que c'est un repo git propre           │
│    - Aucune URL distante acceptée en entrée                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. DÉTECTION (outils matures, pas de LLM)                    │
│    - bandit sur les .py                                      │
│    - semgrep avec rules p/security-audit                     │
│    - cppcheck sur les .c/.cpp/.h                             │
│    - Parsing des outputs JSON/XML -> Finding[] (schema)      │
│    - Cap à N findings par run (éviter flood LLM)             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. REMEDIATION (LLM assist)                                  │
│    Pour chaque Finding :                                     │
│    a. Extract context code (±10 lignes autour du finding)   │
│    b. Prompt LLM : "voici un finding [rule_id] [desc],      │
│       propose un diff unifié + explication 2 phrases"        │
│    c. LLM répond avec diff + explication                     │
│    d. Validation : diff parsable, affecte UNIQUEMENT le     │
│       fichier mentionné, pas de hunks hors zone             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. SANDBOX (validation mécanique)                            │
│    a. git worktree add /tmp/aixcc-validate-xxx               │
│    b. Apply patch dans le worktree                           │
│    c. Re-run les détecteurs : le finding ciblé disparaît ?  │
│    d. Run suite de tests du projet (pytest/cargo/make test) │
│    e. Verdict : PASS (finding gone + tests vert) / FAIL     │
│    f. git worktree remove                                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. RAPPORT                                                   │
│    - Markdown : 1 section par finding avec patch + verdict   │
│    - Export DB ctf_reports (réutilise le schema existant :   │
│      tool="aixcc_agent", findings remplies, session_id       │
│      = aixcc-<repo_name>-<timestamp>)                       │
│    - PAS d'auto-commit du patch dans le repo utilisateur     │
│      (le dev applique manuellement ceux qu'il valide)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Schéma de données

### Finding

```python
@dataclass
class Finding:
    detector: str            # "bandit" | "semgrep" | "cppcheck"
    rule_id: str             # "B105", "python.lang.security.audit.xxx"
    severity: str            # "critical" | "high" | "medium" | "low"
    file: str                # chemin relatif au repo
    line: int
    column: int = 0
    description: str = ""
    cwe: Optional[str] = None     # "CWE-78"
    code_context: str = ""        # extrait ±10 lignes
```

### Patch

```python
@dataclass
class Patch:
    finding_id: str              # hash(detector + rule_id + file + line)
    diff_unified: str            # contenu d'un .patch parsable
    explanation: str             # 2-3 phrases pédagogiques
    affected_files: list[str]    # extrait du diff
    llm_model: str               # modèle qui a produit le patch
    llm_tokens: int = 0
```

### TestResult

```python
@dataclass
class TestResult:
    finding_gone: bool           # le détecteur ne ré-émet plus le finding
    tests_pass: bool             # la suite de tests du repo passe
    tests_runner: str            # "pytest" | "cargo test" | "make test"
    tests_duration_s: float
    tests_stdout_tail: str       # dernières 50 lignes pour debug
    verdict: str                 # "pass" | "fail_tests" | "fail_still_vuln"
```

---

## 5. Garde-fous

### Validation entrée (repo.py)

- **Doit** être un chemin local absolu
- **Doit** être un repo git (`.git/` présent)
- **Doit** avoir un working tree propre (pas de modifications non-commitées)
- **Rejeté** si le path contient des patterns suspects (symlinks sortants du repo)
- **Rejeté** si c'est une URL (`http://`, `git@`, etc.) — pas de clone distant
- **Rejeté** si le repo dépasse une taille limite (ex: 1 GB) pour éviter
  le wrapping sur des monorepos géants

### LLM prompt (patcher.py)

Le prompt système est figé et inclut :

```
Tu es un assistant de remediation de code. On te présente un finding
d'un linter de sécurité avec le code source concerné. Ta tâche unique
est de proposer un diff unifié minimal qui corrige ce finding spécifique.

Contraintes strictes :
- Le diff ne doit affecter QUE le fichier : {file}
- Le diff ne doit modifier QUE les lignes autour de : {line} (±20 max)
- Tu ne dois PAS refactorer d'autres parties du code
- Tu ne dois PAS créer de nouveaux fichiers
- Tu ne dois PAS modifier les tests existants
- Si tu ne sais pas corriger avec certitude, réponds "SKIP: <raison>"

Format de réponse :
--- DIFF ---
<diff unifié valide>
--- EXPLANATION ---
<2-3 phrases en français>
```

Le LLM ne reçoit JAMAIS :
- Le code source complet du repo (seulement `code_context` de 20 lignes)
- Les credentials/env vars du projet
- La structure d'autres fichiers
- Une demande "trouve d'autres failles"

### Validation de la sortie LLM (patcher.py)

Avant d'appliquer un patch, on vérifie :

1. Le diff parse bien avec `patch --dry-run`
2. Le diff ne contient qu'un seul fichier et c'est bien celui attendu
3. Le nombre de lignes modifiées est ≤ 40 (sanity)
4. Aucun nouveau fichier créé (pas de section `new file mode`)
5. Aucun fichier supprimé
6. Aucun symlink créé

Si une de ces vérifications échoue, le patch est rejeté et marqué "SKIPPED
— patch invalide" dans le rapport.

### Sandbox (sandbox.py)

- Utilise `git worktree` (pas de clone, pas de copie de fichiers)
- Le worktree est dans `/tmp/aixcc-validate-<uuid>/`
- Lancé avec un timeout strict (défaut 5 min pour les tests)
- Resources capées : `ulimit -v 2GB` pour éviter OOM
- **PAS** de network access depuis le sandbox (pas utile pour patch
  generation, et réduit la surface)
- Le worktree est nettoyé même en cas de crash (try/finally + atexit)

### Aucun auto-commit

- L'outil **ne fait jamais** `git commit` ou `git push` dans le repo utilisateur
- Il produit un fichier `aixcc-patches-<timestamp>.md` avec les diffs
- Le dev applique lui-même ceux qu'il valide via `git apply`

---

## 6. Configuration LLM

Le module réutilise `NokidoAgent` (déjà présent) via `llm_client.py`.
Policies par défaut :

```python
# config.py
LLM_BACKEND_ORDER = ["ollama", "github", "azure", "groq"]
LLM_MODEL_DEFAULT = "qwen2.5-coder:7b"   # local d'abord
LLM_MAX_TOKENS = 800                     # un patch n'a pas besoin de 5000 tokens
LLM_TEMPERATURE = 0.1                    # déterministe
LLM_TIMEOUT_S = 60
```

Cascade optionnelle :
- Qwen local propose le patch
- Si le finding a `severity=critical` **et** Qwen répond "SKIP", on peut
  escalader vers GitHub Models/GPT-4o-mini pour 2e avis
- Jamais d'escalade automatique hors des critical

---

## 7. CLI

```bash
# Usage minimal
python -m app.aixcc_agent /path/to/repo

# Avec options
python -m app.aixcc_agent /path/to/repo \
  --detectors bandit,semgrep \
  --max-findings 20 \
  --llm-backend ollama \
  --skip-tests \
  --output /tmp/report.md

# Dry-run : détecte + propose patchs mais ne sandbox pas
python -m app.aixcc_agent /path/to/repo --dry-run

# Single finding : pour un run ciblé
python -m app.aixcc_agent /path/to/repo --finding bandit:B105:src/auth.py:42
```

Codes de sortie :
- `0` : aucun finding détecté
- `1` : findings détectés et tous patchables (verdict=pass)
- `2` : findings détectés, certains non-patchables (verdict=fail)
- `3` : erreur d'exécution (repo invalide, LLM indisponible, etc.)

---

## 8. Intégration avec Nokido existant

### Réutilisation

- `app.core.llm` (via `NokidoAgent`) pour les appels LLM
- `app.ctf_reports.storage.CtfReportStorage` pour persister le run
  comme une session CTF (tool="aixcc_agent")
- `app.ctf_reports.views.router` pour consulter les runs dans l'UI
  `/reports` existante
- `app.web_hub.auth` héritée si on ajoute un endpoint plus tard
  (voir section 10)

### Nouveau module isolé

- `app/aixcc_agent/` est auto-contenu
- Aucune dépendance cyclique : importe depuis `app/ctf_reports/` et
  `app/core/llm/`, mais rien n'importe depuis `aixcc_agent/`

---

## 9. Ce qui est hors scope

Ces features ne doivent PAS être ajoutées, même si elles semblent "utiles" :

- ❌ Détection LLM à vide ("trouve des failles dans ce code")
- ❌ Clone d'un repo distant depuis une URL
- ❌ Scan d'un système en production
- ❌ Génération d'exploits (PoC)
- ❌ Auto-commit / auto-push des patchs
- ❌ Endpoint d'upload de code source via HTTP
- ❌ Support d'entrée "juste un fichier" (l'outil exige un repo git pour
  la validation par tests — un fichier isolé sans tests ne permet pas
  de valider la non-régression)
- ❌ Intégration avec scanners dynamiques (DAST) : Burp, ZAP, sqlmap
- ❌ Plugin IDE qui exécuterait automatiquement (trop de surface)

Si une de ces fonctions est demandée plus tard, **relire le doc
ensemble** avant d'implémenter.

---

## 10. Exposition via le hub (optionnel, phase 2)

Si un jour tu veux exposer l'outil via l'UI /reports, le contrat doit être :

- **Pas d'endpoint `POST /aixcc/run`** qui lancerait l'agent à la demande HTTP.
- À la place, un **job queue** : tu lances `python -m app.aixcc_agent` en CLI,
  le run se persiste dans la DB ctf_reports, et l'UI affiche le rapport
  comme pour CAI.
- Même principe que la Couche A : Nokido n'opère pas l'outil via HTTP, il
  archive ce que l'utilisateur a lancé manuellement.

Cette contrainte évite qu'un attaquant qui compromet le hub puisse déclencher
des scans/patches arbitraires.

---

## 11. Tests d'acceptation qui doivent tous passer avant merge

Avant de considérer le module "livré", ces tests NR doivent tous être verts.
Ils forment le contrat de sécurité du module.

### Tests repo validation

- `test_repo_rejects_url_input` : passer `https://github.com/x/y` → erreur
- `test_repo_rejects_non_git_dir` : passer `/tmp/empty/` → erreur
- `test_repo_rejects_dirty_working_tree` : repo avec changements non-commités → erreur
- `test_repo_rejects_symlink_escape` : symlink qui pointe hors du repo → erreur
- `test_repo_rejects_too_large` : repo >1GB → erreur

### Tests détection

- `test_bandit_parses_b105_finding` : fake code avec hardcoded password,
  finding B105 retourné avec line/file corrects
- `test_semgrep_parses_sqli_finding` : fake code vulnérable, finding parsé
- `test_findings_capped_at_max` : si 200 findings, seulement MAX_FINDINGS remontent
- `test_no_detector_silent_mode` : aucun détecteur installé → log + 0 findings,
  pas de crash

### Tests patcher (LLM)

- `test_patcher_rejects_multi_file_diff` : LLM répond avec un diff sur 2
  fichiers → patch marqué invalide
- `test_patcher_rejects_new_file_creation` : diff contient `new file mode` → invalide
- `test_patcher_rejects_oversized_diff` : diff de 100 lignes → invalide
- `test_patcher_accepts_minimal_diff` : diff propre de 5 lignes → accepté
- `test_patcher_skip_response_handled` : LLM répond "SKIP: uncertain" → patch.diff vide

### Tests sandbox

- `test_sandbox_uses_git_worktree_not_clone` : verify worktree, pas de copy
- `test_sandbox_has_no_network` : `curl https://google.com` échoue dans la sandbox
- `test_sandbox_timeout_kills_tests` : tests qui bouclent → killés à
  `TESTS_TIMEOUT_S`
- `test_sandbox_cleanup_on_crash` : si crash à mi-chemin, worktree supprimé
- `test_sandbox_no_autocommit` : après le run, `git log` du repo utilisateur
  inchangé

### Tests intégration

- `test_run_on_fake_vuln_repo_produces_report` : repo de test avec 1 vuln connue,
  run complet → rapport .md produit avec diff pertinent
- `test_run_exports_to_ctf_reports_db` : après le run, la session apparaît dans
  la DB avec tool="aixcc_agent"
- `test_run_no_commit_on_utilisateur_repo` : après le run, `git status` du repo
  est propre

### Tests garde-fous stricts

- `test_no_post_endpoint_exposed` : le module n'expose AUCUN endpoint HTTP
  (on vérifie statiquement qu'il n'y a pas de `@router.post` / `@app.post`)
- `test_no_outbound_http_in_detection` : mock HTTP → aucune requête sortante
  pendant la détection
- `test_llm_prompt_does_not_leak_full_source` : le prompt envoyé au LLM
  contient bien ≤ 20 lignes de code_context, pas le fichier complet
- `test_llm_prompt_does_not_ask_for_exploit` : le prompt système ne contient
  aucun mot clef comme "exploit", "payload", "attack"

---

## 12. Étapes d'implémentation suggérées

Quand tu seras prêt à coder, je suggère cet ordre :

1. **Squelette** : `config.py`, `schema.py`, `__init__.py`
2. **repo.py** : validation inputs + tests NR correspondants
3. **detectors/bandit.py** seul d'abord (plus simple) + NR
4. **detectors/semgrep.py** + NR
5. **schema + storage** : intégration avec `ctf_reports.storage`
6. **patcher.py** : prompt + validation diff + NR (mock LLM d'abord)
7. **sandbox.py** : git worktree + run tests + NR
8. **reporter.py** : markdown export + export DB
9. **cli.py** : entrypoint final
10. **Tests d'intégration** end-to-end

Ne fais pas les étapes dans le désordre. En particulier, **ne pas commencer
par le patcher** (LLM part) avant que repo.py + detectors + sandbox ne soient
tous verts — sinon le patcher tournera sans garde-fous mécaniques autour.

---

## 13. Ce que je recommande si tu veux le développer plus tard

1. **Relire ce doc intégralement** avant de commencer à coder
2. **Cloner un repo de test volontairement vulnérable** pour les tests NR :
   - OWASP WebGoat (Java — hors scope si tu ne supportes que Python/C)
   - Damn Vulnerable Python App (DVPA)
   - Ou monter ton propre `sandbox/aixcc_test_repos/tiny-vuln-py/`
3. **Ne pas utiliser ce module sur du code dont tu n'as pas les droits**
4. **Tenir à jour la liste des plateformes sous scope AIxCC officiel**
   au fur et à mesure que les rounds s'annoncent
5. **Si tu ajoutes un détecteur** (ex: `rubocop`, `eslint-security`) :
   même adapter pattern, mêmes tests d'acceptation
6. **Si tu as un doute sur une feature** (ex: "je voudrais que ça tourne
   automatiquement sur un cron"), relire la section "Ce qui est hors scope"
   avant de coder

---

## 14. Pourquoi ce cadrage est strict

Cet outil est à la limite fine entre **assistant DevSecOps légitime**
(ce que sont bandit/semgrep + copilot aujourd'hui) et **agent
offensif** (ce que deviendrait le même code si on enlevait les garde-fous).

La différence tient en quelques lignes :
- **Entrée repo local + tests mécaniques existants** → assistant
- **Entrée URL + scan réseau** → scanner offensif
- **LLM patch avec contexte 20 lignes** → assistant
- **LLM "trouve des failles" sans contexte** → détecteur polyvalent
- **Sandbox sans réseau** → validation defense
- **Sandbox avec réseau** → staging d'attaque

Garde cette grille en tête chaque fois que tu modifies le module. Si une
modification fait glisser vers la droite de ces oppositions, c'est
probablement un mauvais changement.

---

## 15. Si tu veux me demander de coder une partie

Je peux implémenter, dans une session future :

- `repo.py` + ses tests (aucun risque, pure validation entrée)
- `detectors/*.py` + tests (pure lecture d'outils existants)
- `schema.py` + `reporter.py` (data + markdown)
- `sandbox.py` + tests (git worktree + subprocess, pas de LLM)

Ce que je ne coderai pas même sur demande :

- `patcher.py` (LLM prompt engineering pour génération de patchs
  automatisés — je peux aider sur le design du prompt, mais je ne
  veux pas être celui qui écrit la boucle "LLM → diff → apply")
- Tout couplage runtime qui retirerait la nature "humain dans la loop"

Tu peux coder `patcher.py` toi-même avec la spec ci-dessus, ou utiliser
un outil existant comme **semgrep-copilot**, **Snyk AI-Fix**, ou
**CodeQL autofix** (GitHub) qui font déjà ça sous responsabilité
d'entreprises établies.

---

## 16. Alternative : juste brancher des outils existants

Plutôt que d'écrire l'agent complet, une approche encore plus safe :

- **Semgrep CI** (gratuit, OSS) détecte les findings
- **CodeQL autofix** (GitHub) propose des patchs (en beta 2026)
- **Snyk Code** (freemium) fait les deux
- **Trivy** pour les scans de dépendances

Nokido peut **consommer** leurs outputs via le même pattern que CAI :
tu lances l'outil dans ton CI, tu déposes le JSON de findings dans
`logs/ctf_imports/semgrep/`, un importeur le transforme en session
ctf_reports, tu consultes dans `/reports`.

Cette approche livre 80% de la valeur, 0% du risque de dériver vers un
détecteur LLM polyvalent. À considérer sérieusement avant de coder
l'agent complet.

---

## Fin du design doc

**Status final** : ce document fige le contrat. Toute implémentation future
doit passer tous les tests de la section 11 avant merge. Tout écart du cadrage
(ajout de détection LLM polyvalente, endpoint HTTP, auto-commit, etc.) doit
faire l'objet d'une relecture de ce doc en entier.

Si dans 6 mois tu relis ça et tu te dis "mais c'était débile cette restriction",
relis la section 14.
