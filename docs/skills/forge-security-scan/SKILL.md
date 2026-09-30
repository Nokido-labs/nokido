---
name: forge-security-scan
description: >
  Analyse statique de qualité et de robustesse du code pour Nokido —
  wrapper d'outils d'analyse (Semgrep, CodeQL) intégré au silo qualité.
  Triggers : revue statique d'un module forge_*.py avant install/commit,
  scan d'un dépôt à ingérer dans le RAG, détection de défauts courants
  et vérification de conformité, complément de Commit Guard AST et
  SkillGuardian, demande "analyse ce code", "revue avant commit",
  "Semgrep / CodeQL sur X", "skill safe à installer ?". Délègue les
  findings au hub via /api/ingest pour persistence RAG et au
  forge_clawhub_bridge pour blocage install si severity élevée.
---

# forge-security-scan — Scan SAST orchestré

## Statut

LIVE — s'appuie sur le SAST DÉJÀ présent dans Nokido (rien à créer) :
`forge_clawhub_bridge.SkillGuardian._sast_scan` (Semgrep, appelé par `review()`),
`app/semantic_scanner.py` (scan AST), le Commit Guard AST de `forge_mcp_registry`,
et le silo `forge_silo_engine.SiloDomain.SECURITY`. Ce skill ORCHESTRE ces capacités
existantes ; Semgrep/CodeQL en complément subprocess pour le taint/dataflow que l'AST
ne capture pas.

## Pré-requis

- `pip install semgrep` (ou `brew install semgrep`)
- CodeQL CLI optionnel (Trail of Bits skills le requièrent pour les
  packs CodeQL avancés)
- Trail of Bits skills clonés : `git clone
  https://github.com/trailofbits/skills` (à scanner via SkillGuardian
  AVANT install via `forge_clawhub_bridge`)

## Quand se déclencher

- L'utilisateur demande un **scan sécurité** sur un fichier ou dépôt.
- Avant install d'une **skill marketplace** depuis ClawHub —
  `forge_clawhub_autoinstall` doit appeler ce skill comme étape Guardian.
- Avant un **commit Nokido** sensible (tools/, app/forge_*).
- L'utilisateur cite **CWE/OWASP/CVE/Semgrep/CodeQL** dans sa demande.
- Détection d'**injection SQL/XSS/SSRF/path-traversal** demandée.

## Workflow

### 1. Choisir le runner selon le contexte

| Contexte | Runner | Profondeur |
|---|---|---|
| Pre-commit rapide | `semgrep --config=auto` | rapide (< 30s) |
| Skill ClawHub avant install | `semgrep --config=p/security-audit` | medium |
| Audit complet d'un module | `semgrep --config=p/owasp-top-ten p/cwe-top-25` | profond |
| Scan multi-langage avec dataflow | CodeQL (via Trail of Bits packs) | très profond |

### 2. Exécuter le scan

```bash
semgrep --config=auto --json --quiet <path> > /tmp/sast_findings.json
```

Pour CodeQL :

```bash
codeql database create db --language=python --source-root=<path>
codeql database analyze db <pack> --format=sarif-latest --output=/tmp/sast.sarif
```

### 3. Parser et persister les findings via le hub

POST sur `/api/ingest` (endpoint existant) avec un payload typé :

```bash
curl -s -X POST http://127.0.0.1:8766/api/ingest \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "source": "sast/semgrep/<scan_id>",
  "kind": "security_finding",
  "items": [
    {"rule": "...", "severity": "HIGH", "file": "...", "line": ...,
     "message": "...", "cwe": "..."}
  ]
}
EOF
```

Les findings deviennent searchables via `rag_fts MATCH 'CWE-89 OR injection'`
et apparaîtront dans le `silo security` lors d'un preflight_check.

### 4. Bloquer l'install si severity >= HIGH

Si appelé depuis le pipeline `forge_clawhub_autoinstall`, retourner un
verdict structuré :

```json
{"verdict": "block", "reason": "2 HIGH findings (CWE-78, CWE-89)",
 "details": [...]}
```

Le bridge `forge_clawhub_bridge.review_and_install()` doit honorer ce
verdict avant l'install.

## Câblage (capacités EXISTANTES — réutiliser, ne rien créer)

- SAST Semgrep : `forge_clawhub_bridge.SkillGuardian._sast_scan` (déjà invoqué par `review()`).
- Scan AST : `app/semantic_scanner.py` + Commit Guard AST (`forge_mcp_registry`).
- Silo sécurité : `forge_silo_engine.SiloDomain.SECURITY` (findings searchables RAG).
- Blocage install severity>=HIGH : `forge_clawhub_bridge` (SkillGuardian.review → reject).
- CodeQL / packs Trail of Bits : subprocess optionnel quand profondeur dataflow requise.

## Anti-patterns

1. **Ne pas faire confiance aveuglément aux findings** — Semgrep/CodeQL
   ont des faux positifs. Toujours review humain pour severity >= HIGH
   avant blocage commit.
2. **Ne pas envoyer le code source brut au cloud** — `forge_semantic_firewall`
   doit redirect (membrane souveraine wrap) avant tout escalade vers un
   LLM cloud pour interprétation des findings.
3. **Ne pas bypasser** ce skill avec `--no-verify` — les Règles d'Or
   Nokido l'interdisent.
4. **Ne pas dupliquer** les capacités existantes : `app/semantic_scanner.py`
   et le Commit Guard AST de `forge_mcp_registry` font déjà du scan AST
   léger. Ce skill ajoute Semgrep/CodeQL pour les patterns que l'AST
   ne capture pas (taint tracking, dataflow inter-procédural).

## Liens

- Trail of Bits skills : https://github.com/trailofbits/skills
- Semgrep registry : https://semgrep.dev/r
- CodeQL : https://codeql.github.com/
- Nokido silo security : `app/forge_silo_engine.py::SiloDomain.SECURITY`
- Nokido Commit Guard AST : `app/forge_mcp_registry.py`
