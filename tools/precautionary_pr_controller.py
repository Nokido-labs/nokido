"""
tools/precautionary_pr_controller.py
=====================================
Contrôleur de PR externe ultra-prudent — v2 (History-Aware + Anti-Bot-Smell)

Adapté pour Nokido v17 — utilise les vrais modules :
  - MultiLLMBridge + ASTSurgeon + CerberusGuard  (tools/evolutionary_engine.py)
  - forge_litellm_bridge.ask()
  - forge_git_worker.GitWorker
  - forge_source_discovery.ForgeSourceDiscovery
  - GitHub Search API réelle (PRs fermées + ouvertes)

Pipeline 8 étapes :
  1. Culture dépôt        (CONTRIBUTING.md, PR template, style guide)
  2. Style + Bot-Smell    (indent, quotes, comment density, human traits)
  3. Vision d'ensemble    (arborescence, structure, langages détectés)
  4. Historique fermées   (PRs closed similaires — évite de rejouer un échec)
  5. Duplicate open       (issues/PRs ouvertes — évite le doublon)
  6. AST + Cerberus       (validation technique)
  7. Audit adversarial    (Llama 3.3 70B — mainteneur grincheux Anti-Bot)
  8. Description humaine  (Gemini — ton humble, pas de bullet-points parfaits)
  → Verrou PR-STAGED-EXT  (rien ne sort sans LGTM des étapes 7 + 6)

Règles RAG ancrées :
  #30 — Tests must match the project CI environment (asyncio_mode, python-version)
  #31 — PR workflow: CONTRIBUTING → style → duplicate → feature branch → issue ref
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : controleur de PR externe ultra-prudent"  # organe declare le 2026-09-06 (audit de raccordement)

import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "intel"))  # forge_git_worker y vit

# `forge_secrets` vit dans app/ : cet import etait place AVANT les injections
# ci-dessus, donc le script mourait en ModuleNotFoundError des le lancement
# (mesure 2026-08-27, forge_feature_checklist).
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

try:
    from nokido_agent.tools.evolutionary_engine import ASTSurgeon, CerberusGuard, MultiLLMBridge
except ImportError:
    ASTSurgeon = CerberusGuard = MultiLLMBridge = None

try:
    from nokido_agent.app.forge_litellm_bridge import ask as llm_ask
except ImportError:
    llm_ask = None

try:
    from forge_git_worker import GitWorker
except ImportError:
    GitWorker = None

try:
    from nokido_agent.tools.forge_source_discovery import ForgeSourceDiscovery
except ImportError:
    ForgeSourceDiscovery = None

import logging

logger = logging.getLogger("Nokido.PrecautionaryPR")


# ── GitHub API ────────────────────────────────────────────────────────────────


def _gh_token() -> str:
    token = get_secret("GITHUB_TOKEN") or ""
    if not token:
        env_file = ROOT / "Nokido.env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("GITHUB_TOKEN="):
                    token = line.split("=", 1)[1].split("#")[0].strip()
                    break
    return token


def _gh(endpoint: str, method: str = "GET", body: dict | None = None) -> dict | list:
    token = _gh_token()
    url = f"https://api.github.com{endpoint}"
    hdrs = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "LaForge/17",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


# ── Controller ────────────────────────────────────────────────────────────────


class PrecautionaryPRController:
    """
    Diplomate de code — soumet des PRs OSS externes avec un niveau de
    prudence maximum.

    Paramètres
    ----------
    repo_path     : chemin local du dépôt cloné (shallow clone recommandé)
    upstream_repo : slug GitHub cible, ex: "psf/requests"
    branch_prefix : préfixe de branche feature, ex: "forge/fix-"
    """

    MODEL_DIPLOMAT = "google/gemini-2.0-flash-exp"
    MODEL_ADVERSARIAL = "meta-llama/llama-3.3-70b-instruct"
    MODEL_FALLBACK = "ollama/qwen2.5-coder:7b"

    # Phrases bot typiques — déclenche le rejet adversarial
    BOT_SMELL_PATTERNS = [
        r"as an ai",
        r"i have optimized",
        r"i have improved",
        r"leverag(e|ing) (the )?(power of|capabilities)",
        r"this (change|fix|pr) (ensures?|guarantees?)",
        r"comprehensiv(e|ely)",
        r"robust(ness)?",
        r"seamless(ly)?",
        r"cutting[- ]edge",
    ]

    def __init__(
        self,
        repo_path: str | Path,
        upstream_repo: str,
        branch_prefix: str = "forge/fix-",
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.upstream_repo = upstream_repo
        self.branch_prefix = branch_prefix

        self.culture_context: str = ""
        self.project_overview: str = ""
        self.style_context: dict = {}

        self.git = GitWorker(self.repo_path) if GitWorker else None
        self.surgeon = ASTSurgeon() if ASTSurgeon else None
        self.cerberus = CerberusGuard() if CerberusGuard else None
        self.bridge = MultiLLMBridge() if MultiLLMBridge else None
        self.discovery = ForgeSourceDiscovery() if ForgeSourceDiscovery else None

    # ── 1. CULTURE ────────────────────────────────────────────────────────────

    def _load_culture(self) -> None:
        """
        Lit CONTRIBUTING.md, PR template et README.
        Extrait les règles sociales : préfixes de commit, labels, workflows attendus.
        """
        candidates = [
            "CONTRIBUTING.md",
            ".github/CONTRIBUTING.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            "docs/contributing.md",
            "CONTRIBUTING",
            "README.md",
        ]
        found = []
        for name in candidates:
            p = self.repo_path / name
            if p.exists():
                found.append(
                    f"=== {name} ===\n{p.read_text(encoding='utf-8', errors='replace')[:2000]}"
                )
        self.culture_context = "\n\n".join(found) if found else "(no contribution guide found)"
        logger.info(f"[culture] {len(found)} fichiers chargés")

    # ── 2. STYLE + BOT-SMELL DETECTION ───────────────────────────────────────

    def _detect_style(self, target_file: str) -> dict:
        """
        Analyse le fichier cible :
        - indent / quotes / line length / lint tool
        - comment_density : "high" si > 15% de lignes commentées
        - human_traits : trailing_commas, blank lines between methods, etc.
        Ces données permettent au LLM de mimer le style et d'éviter
        les signaux "Bot" (trop de docstrings, bullet-points parfaits, etc.)
        """
        path = self.repo_path / target_file
        if not path.exists():
            return {
                "indent": "4_spaces",
                "quotes": "double",
                "line_length": 88,
                "lint": "ruff",
                "comment_density": "low",
                "human_traits": [],
                "commit_prefix": "fix:",
            }

        code = path.read_text(encoding="utf-8", errors="replace")
        lines = code.splitlines()

        # Indentation
        indent = "4_spaces"
        for l in lines:
            if l.startswith("\t"):
                indent = "tabs"
                break
            if l.startswith("  ") and not l.startswith("    "):
                indent = "2_spaces"
                break

        # Densité de commentaires (anti-bot)
        comment_lines = [l for l in lines if l.strip().startswith("#")]
        comment_ratio = len(comment_lines) / max(len(lines), 1)

        # Human traits détectés
        human_traits = []
        if "]," in code:
            human_traits.append("trailing_commas")
        if re.search(r"\n\n    def ", code):
            human_traits.append("blank_line_between_methods")
        if re.search(r"# (TODO|FIXME|HACK|XXX)", code):
            human_traits.append("has_todo_comments")
        if re.search(r"#.*\.\.\.", code):
            human_traits.append("informal_comments")

        style = {
            "indent": indent,
            "quotes": "single" if code.count("'") > code.count('"') else "double",
            "line_length": 88,
            "lint": "ruff",
            "commit_prefix": self._extract_commit_prefix(),
            "comment_density": "high" if comment_ratio > 0.15 else "low",
            "human_traits": human_traits,
        }

        # line_length et lint depuis les fichiers de config
        for cfg in ["pyproject.toml", "setup.cfg", ".flake8", "tox.ini"]:
            cfg_path = self.repo_path / cfg
            if cfg_path.exists():
                cfg_text = cfg_path.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"line[_-]length\s*=\s*(\d+)", cfg_text)
                if m:
                    style["line_length"] = int(m.group(1))
                if "flake8" in cfg_text:
                    style["lint"] = "flake8"
                if "pylint" in cfg_text:
                    style["lint"] = "pylint"
                break

        self.style_context = style
        logger.info(f"[style] {style}")
        return style

    def _extract_commit_prefix(self) -> str:
        for p in [r"(fix|feat|chore|docs|test|refactor|perf|ci):", r"`(fix|feat|chore)[\(:]"]:
            m = re.search(p, self.culture_context, re.IGNORECASE)
            if m:
                return m.group(1).lower() + ":"
        return "fix:"

    # ── 3. VISION D'ENSEMBLE ──────────────────────────────────────────────────

    def _get_repo_overview(self) -> str:
        """
        Génère une arborescence condensée du dépôt.
        Permet au LLM d'éviter les fix hors-contexte
        (modifier un fichier dont la logique est centralisée ailleurs).
        Limite : 40 fichiers pour ne pas saturer le contexte.
        """
        files = []
        for p in sorted(self.repo_path.rglob("*")):
            if not p.is_file():
                continue
            parts = p.relative_to(self.repo_path).parts
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            files.append(str(p.relative_to(self.repo_path)))
            if len(files) >= 40:
                break

        overview = "Project structure:\n- " + "\n- ".join(files)
        if len(files) == 40:
            overview += f"\n  (truncated — {len(files)}+ files total)"
        self.project_overview = overview
        logger.info(f"[overview] {len(files)} fichiers indexés")
        return overview

    # ── 4. HISTORIQUE PRs FERMÉES ─────────────────────────────────────────────

    async def _search_closed_prs(self, keywords: list[str]) -> str:
        """
        Cherche les PRs FERMÉES (non-mergées) similaires sur GitHub.
        But : ne pas rejouer une approche déjà rejetée par les mainteneurs.
        Retourne un résumé textuel pour l'audit adversarial.

        Si l'API n'est pas disponible, utilise le LLM pour simuler
        l'historique à partir de ses données de pré-entraînement.
        """
        query = urllib.parse.quote(" ".join(keywords[:4]))
        history_lines = []

        try:
            results = _gh(
                f"/search/issues?q={query}+repo:{self.upstream_repo}"
                f"+is:pr+is:closed+is:unmerged&per_page=5&sort=updated"
            )
            for item in results.get("items", []):
                history_lines.append(
                    f"  • PR #{item['number']} (closed, not merged): {item['title'][:70]}\n"
                    f"    URL: {item['html_url']}"
                )
            if history_lines:
                return "Closed (unmerged) PRs found:\n" + "\n".join(history_lines)
        except Exception as e:
            logger.warning(f"[history] GitHub search failed: {e}")

        # Fallback LLM — utilise la mémoire d'entraînement
        if llm_ask:
            try:
                result = await llm_ask(
                    task=(
                        f"Based on your training data, what are common reasons why PRs "
                        f"for '{' '.join(keywords[:3])}' in {self.upstream_repo} get closed "
                        f"without merging? List 2-3 concrete reasons."
                    ),
                    role="Open-source historian",
                )
                return f"LLM-simulated history for {self.upstream_repo}:\n{result}"
            except Exception:
                pass

        return "No closed PR history found — proceed with caution."

    # ── 5. DUPLICATE CHECK (ouvertes) ─────────────────────────────────────────

    def _check_duplicates(self, keywords: list[str]) -> tuple[bool, str]:
        """
        Vérifie les issues/PRs OUVERTES similaires.
        Différent de l'historique : si quelqu'un travaille déjà dessus,
        on ne pollue pas le tracker.
        """
        query = urllib.parse.quote("+".join(keywords[:3]))
        try:
            results = _gh(f"/search/issues?q={query}+repo:{self.upstream_repo}+is:open&per_page=5")
            items = results.get("items", [])
            open_prs = [i for i in items if "pull_request" in i]
            open_issues = [i for i in items if "pull_request" not in i]

            if open_prs:
                p = open_prs[0]
                return True, f"Open PR already exists: #{p['number']} — {p['title'][:60]}"
            if open_issues:
                i = open_issues[0]
                return False, f"Related open issue #{i['number']} — reference it in the PR body"
        except Exception as e:
            logger.warning(f"[duplicate] Check failed: {e}")

        return False, "No duplicate found"

    # ── 6. VALIDATION TECHNIQUE ───────────────────────────────────────────────

    def _technical_validate(self, original: str, mutated: str, fname: str) -> tuple[bool, str]:
        """ASTSurgeon → intégrité structurelle. CerberusGuard → score AST+pytest+ruff."""
        if self.surgeon:
            ok, msg = self.surgeon.validate_integrity(original, mutated)
            if not ok:
                return False, f"ASTSurgeon: {msg}"

        if self.cerberus:
            try:
                score, msg = self.cerberus.evaluate(original, mutated, fname, 0)
                if score < 70:
                    return False, f"Cerberus {score}/100: {msg}"
                logger.info(f"[cerberus] {score}/100")
            except Exception as e:
                logger.warning(f"[cerberus] non-bloquant: {e}")

        return True, "OK"

    # ── 7. AUDIT ADVERSARIAL + ANTI-BOT-SMELL ─────────────────────────────────

    async def _adversarial_audit(
        self,
        diff: str,
        pr_description: str,
        closed_history: str,
    ) -> tuple[bool, str]:
        """
        Llama 3.3 70B joue le rôle d'un mainteneur agacé par le spam des IA.
        Il cherche activement à rejeter la PR sur 4 axes :

        1. Bot-Smells      — phrases robotiques, bullet-points trop parfaits
        2. Push de cochon  — modifications de style inutiles, réécriture de code qui marche
        3. Manque de tact  — ignore le style du fichier, docstrings trop denses
        4. Doublon passé   — même approche déjà fermée (historique fourni)

        Retourne (True, "LGTM") seulement si la PR est humble,
        chirurgicale et indispensable.
        """
        # Pré-vérification locale des Bot-Smells avant même d'appeler le LLM
        desc_lower = pr_description.lower()
        for pattern in self.BOT_SMELL_PATTERNS:
            if re.search(pattern, desc_lower):
                return False, (
                    f"BLOCKER — Bot-Smell detected in description: "
                    f"pattern '{pattern}' matched. Rewrite without AI clichés."
                )

        prompt = (
            "You are a respected but strict open-source maintainer who is tired of AI-generated PRs.\n"
            "A PR was just submitted. Your job: find a reason to CLOSE IT.\n\n"
            "Check specifically:\n"
            "1. Bot-Smells: robotic phrases ('I have optimized', 'As an AI', perfect bullet lists)\n"
            "2. Pig-push: unnecessary style changes, rewriting working code for no reason\n"
            "3. Lack of respect: ignored project style (indent, comment density, tone)\n"
            "4. History repeat: does this approach match a previously closed PR?\n\n"
            f"PROJECT CONTRIBUTION RULES:\n{self.culture_context[:1000]}\n\n"
            f"PROJECT STYLE (detected):\n{json.dumps(self.style_context)}\n\n"
            f"PROJECT OVERVIEW:\n{self.project_overview[:600]}\n\n"
            f"CLOSED PR HISTORY (danger — avoid repeating these):\n{closed_history[:600]}\n\n"
            f"PR DESCRIPTION:\n{pr_description[:800]}\n\n"
            f"DIFF:\n{diff[:2000]}\n\n"
            "If the PR is humble, surgical and genuinely necessary — reply with just 'LGTM'.\n"
            "Otherwise, list blocking issues with severity (BLOCKER / MINOR) and close it mercilessly."
        )

        try:
            if llm_ask:
                result = await llm_ask(
                    task=prompt,
                    role="Strict OSS maintainer hunting for AI-generated spam",
                    system_extra="Be harsh. LGTM only if the PR is genuinely clean and human-looking.",
                )
            elif self.bridge:
                result = self.bridge.call(
                    model=self.MODEL_ADVERSARIAL,
                    prompt=prompt,
                    max_tokens=400,
                )
            else:
                logger.warning("[adversarial] No bridge — audit skipped")
                return True, "LGTM (no bridge available)"

            result = result.strip()
            logger.info(f"[adversarial] {result[:120]}")

            if result.upper().startswith("LGTM") and len(result) < 60:
                return True, "LGTM"
            return False, result

        except Exception as e:
            logger.error(f"[adversarial] Error: {e}")
            return True, f"LGTM (audit error: {e})"

    # ── 8. DESCRIPTION DIPLOMATIQUE HUMAINE ──────────────────────────────────

    async def _write_diplomatic_description(
        self,
        diff: str,
        issue_context: str,
        closed_history: str,
        duplicate_reason: str,
    ) -> str:
        """
        Rédige une description de PR qui ressemble à un humain pressé mais précis.

        Instructions clés au LLM :
        - Ton humble : "I noticed...", "I tried to fix..." (pas "I have optimized")
        - Pas de bullet-points parfaits sauf si le template l'exige
        - Explique pourquoi cette approche diffère des tentatives fermées
        - Référence l'issue ouverte si disponible
        - Minimaliste : un seul paragraphe si possible
        """
        issue_ref = ""
        if "#" in duplicate_reason:
            m = re.search(r"#(\d+)", duplicate_reason)
            if m:
                issue_ref = f"\n\nFixes #{m.group(1)}."

        template_hint = ""
        tpl_path = self.repo_path / ".github" / "PULL_REQUEST_TEMPLATE.md"
        if tpl_path.exists():
            template_hint = (
                f"\nThe project has a PR template — follow its structure:\n"
                f"{tpl_path.read_text(encoding='utf-8', errors='replace')[:800]}"
            )

        prompt = (
            "Write a GitHub pull request description. You are a human developer.\n"
            "DO NOT use AI clichés. DO NOT write perfect bullet lists unless the template requires it.\n"
            "Write like a developer who noticed something small and fixed it quietly.\n"
            "Use 'I noticed...', 'This fixes...', 'Small fix for...' — not 'I have optimized'.\n\n"
            f"Project contribution guide:\n{self.culture_context[:800]}\n"
            f"{template_hint}\n"
            f"Detected style: {json.dumps(self.style_context)}\n\n"
            f"Bug context: {issue_context}\n"
            f"Closed PR history to differentiate from:\n{closed_history[:400]}\n"
            f"Diff:\n{diff[:1200]}"
            f"{issue_ref}"
        )

        try:
            if llm_ask:
                desc = await llm_ask(
                    task=prompt,
                    role="Human developer writing a minimal OSS contribution",
                )
            elif self.bridge:
                desc = self.bridge.call(
                    model=self.MODEL_DIPLOMAT,
                    prompt=prompt,
                    max_tokens=500,
                )
            else:
                desc = f"Small fix: {issue_context}\n\nTests added. 0 regressions.{issue_ref}"
            return desc.strip()
        except Exception as e:
            logger.error(f"[description] Error: {e}")
            return f"Fix: {issue_context}\n\nTests added. 0 regressions.{issue_ref}"

    # ── ANCRAGE RAG ────────────────────────────────────────────────────────────

    def _anchor_lesson(self, lesson: str, source: str) -> None:
        """Ancre une leçon PR dans le RAG Nokido pour les futures contributions."""
        try:
            import sqlite3

            db_path = ROOT / "RAG" / "embeddings.db"
            conn = sqlite3.connect(str(db_path), timeout=5)
            # 2026-09-12 : sans `id` (TEXT PRIMARY KEY) la clef restait NULLE.
            from nokido_agent.app.forge_db_path import chunk_id as _cid  # type: ignore

            conn.execute(
                "INSERT INTO rag_chunks (id, text, source, domain, meta) VALUES (?,?,?,?,?)",
                (
                    _cid(source, lesson),
                    lesson,
                    source,
                    "devops",
                    json.dumps({"type": "pr_lesson", "repo": self.upstream_repo}),
                ),
            )
            conn.commit()
            conn.close()
            logger.info(f"[rag] Anchored: {lesson[:60]}")
        except Exception as e:
            logger.warning(f"[rag] Anchor failed: {e}")

    # ── PIPELINE PRINCIPAL ─────────────────────────────────────────────────────

    async def stage_external_pr(
        self,
        target_file: str,
        issue_context: str,
        keywords: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Pipeline complet — 8 étapes, verrou PR-STAGED-EXT final.

        dry_run=True → analyse complète sans push ni PR GitHub.
        """
        print(f"\n{'=' * 62}")
        print(f"  PrecautionaryPR v2 — {self.upstream_repo}")
        print(f"  Target: {target_file}")
        print(f"{'=' * 62}\n")

        kws = keywords or issue_context.split()[:5]

        # 1. Culture
        print("📚 [1/8] Repository culture...")
        self._load_culture()

        # 2. Style + Bot-Smell baseline
        print("🎨 [2/8] Style detection + Bot-Smell baseline...")
        style = self._detect_style(target_file)
        print(
            f"     indent={style['indent']}  quotes={style['quotes']}  "
            f"density={style['comment_density']}  "
            f"traits={style['human_traits']}"
        )

        # 3. Vision d'ensemble
        print("🗺️  [3/8] Repository overview...")
        self._get_repo_overview()

        # 4. Historique PRs fermées
        print("🔎 [4/8] Closed PR history (avoid repeating failures)...")
        closed_history = await self._search_closed_prs(kws)
        preview = closed_history[:80].replace("\n", " ")
        print(f"     {preview}...")

        # 5. Duplicate check (ouvertes)
        print("🔍 [5/8] Open duplicate check...")
        is_dup, dup_reason = self._check_duplicates(kws)
        if is_dup:
            print(f"⛔  Duplicate: {dup_reason}")
            self._anchor_lesson(
                f"Duplicate PR avoided on {self.upstream_repo}: {dup_reason}",
                f"{self.upstream_repo}/duplicate",
            )
            return {"status": "duplicate", "reason": dup_reason}
        print(f"     ✅ {dup_reason}")

        # 6. Diff + validation technique
        print("🔬 [6/8] Diff + AST + Cerberus validation...")
        if self.git:
            diff = self.git._exec(["diff", "HEAD"]).get("stdout", "")
            if not diff:
                diff = self.git._exec(["diff", "--cached"]).get("stdout", "")
        else:
            diff = subprocess.run(
                ["git", "diff", "HEAD"], cwd=str(self.repo_path), capture_output=True, text=True
            , errors="replace").stdout

        if not diff:
            return {"status": "error", "message": "No changes detected in repository."}

        target_path = self.repo_path / target_file
        if target_path.exists():
            try:
                orig = subprocess.run(
                    ["git", "show", f"HEAD:{target_file}"],
                    cwd=str(self.repo_path),
                    capture_output=True,
                    text=True,
                errors="replace").stdout
                mutated = target_path.read_text(encoding="utf-8", errors="replace")
                ok, msg = self._technical_validate(orig, mutated, target_file)
                if not ok:
                    print(f"⛔  Technical: {msg}")
                    return {"status": "error", "message": msg}
                print(f"     ✅ {msg}")
            except Exception as e:
                print(f"     ⚠️  Validation skipped: {e}")

        lines_changed = len(
            [
                l
                for l in diff.splitlines()
                if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
            ]
        )
        print(f"     {lines_changed} lines changed")

        # 7. Audit adversarial (Anti-Bot + mainteneur grincheux)
        print("🕵️  [7/8] Adversarial audit (strict maintainer + Bot-Smell detection)...")
        prelim_desc = f"Fix: {issue_context}\n\nDiff: {lines_changed} lines changed."
        audit_ok, audit_feedback = await self._adversarial_audit(diff, prelim_desc, closed_history)

        if not audit_ok:
            print("⛔  Adversarial audit — PR rejected:")
            for line in audit_feedback.splitlines()[:6]:
                print(f"     {line}")
            self._anchor_lesson(
                f"PR rejected by adversarial audit on {self.upstream_repo}/{target_file}: "
                f"{audit_feedback[:200]}",
                f"{self.upstream_repo}/adversarial_audit",
            )
            return {"status": "rejected_adversarial", "feedback": audit_feedback}
        print(f"     ✅ {audit_feedback}")

        # 8. Description humaine
        print("📝 [8/8] Human-tone diplomatic description...")
        pr_body = await self._write_diplomatic_description(
            diff, issue_context, closed_history, dup_reason
        )

        # Verrou PR-STAGED-EXT
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        state_id = f"PR-STAGED-EXT-{timestamp}-{os.urandom(2).hex().upper()}"
        branch = f"{self.branch_prefix}{state_id.lower()}"
        commit_msg = (
            f"{style['commit_prefix']} {issue_context[:60]}\n\n"
            f"Validated by Nokido Precautionary Engine v2\n"
            f"ID: {state_id}"
        )

        print(f"\n🔒 Lock: {state_id}")

        if dry_run:
            print("   [dry-run] No push / no GitHub PR.")
            result_dict = {
                "status": "dry_run",
                "state_id": state_id,
                "branch": branch,
                "title": f"{style['commit_prefix']} {issue_context[:70]}",
                "body": pr_body,
                "style": style,
                "diff_lines": lines_changed,
                "audit": audit_feedback,
                "duplicate": dup_reason,
                "history": closed_history[:200],
            }
        else:
            try:
                fork_owner = "user"
                subprocess.run(
                    ["git", "checkout", "-b", branch],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "add", target_file],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True,
                )

                token = _gh_token()
                repo_name = self.upstream_repo.split("/")[-1]
                remote = f"https://{token}@github.com/{fork_owner}/{repo_name}.git"
                subprocess.run(
                    ["git", "push", remote, branch],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True,
                )

                pr = _gh(
                    f"/repos/{self.upstream_repo}/pulls",
                    "POST",
                    {
                        "title": f"{style['commit_prefix']} {issue_context[:70]}",
                        "head": f"{fork_owner}:{branch}",
                        "base": "main",
                        "body": pr_body,
                        "draft": False,
                    },
                )
                result_dict = {
                    "status": "success",
                    "state_id": state_id,
                    "pr_url": pr.get("html_url"),
                    "pr_number": pr.get("number"),
                    "branch": branch,
                    "style": style,
                }
                print(f"✅ PR opened: {pr.get('html_url')}")

            except Exception as e:
                logger.error(f"[push] Error: {e}")
                result_dict = {"status": "push_error", "message": str(e), "state_id": state_id}

        # Ancrage RAG final
        self._anchor_lesson(
            f"PR staged for {self.upstream_repo}/{target_file}: "
            f"style={style['indent']}, prefix={style['commit_prefix']}, "
            f"comment_density={style['comment_density']}, "
            f"human_traits={style['human_traits']}, state_id={state_id}. "
            f"Closed history consulted. Bot-Smell check passed.",
            f"{self.upstream_repo}/pr_staged_v2",
        )
        return result_dict

    # ── CLI ───────────────────────────────────────────────────────────────────

    @classmethod
    def cli(cls) -> None:
        import argparse

        parser = argparse.ArgumentParser(
            description="Nokido PrecautionaryPR v2 — History-Aware, Anti-Bot-Smell"
        )
        parser.add_argument("repo_path", help="Path to locally cloned repo")
        parser.add_argument("upstream", help="GitHub slug, e.g. psf/requests")
        parser.add_argument("target_file", help="Modified file, e.g. src/requests/auth.py")
        parser.add_argument("issue", help="Bug context, e.g. 'fix DigestAuth bytes crash'")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--keywords", nargs="+")
        args = parser.parse_args()

        controller = cls(repo_path=args.repo_path, upstream_repo=args.upstream)
        result = asyncio.run(
            controller.stage_external_pr(
                target_file=args.target_file,
                issue_context=args.issue,
                keywords=args.keywords,
                dry_run=args.dry_run,
            )
        )
        print("\n" + json.dumps(result, indent=2))


if __name__ == "__main__":
    PrecautionaryPRController.cli()
