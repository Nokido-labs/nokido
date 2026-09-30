"""forge_skill_sync.py — Matérialiseur de skills cross-CLI souverain.

__FORGE_COLOR__ = "skill-management"

POURQUOI un nouveau module (anti-dup CLAUDE.md §3) — vérifié 2026-06-10 :
  - hub tool `skill` (app/forge_handler_skill.handle_skill) = registre central LECTURE
    (action=list|load|search|ingest ; source = rag_chunks domain='skill' + docs/skills/).
  - app/forge_skill_enricher.py = leçons → propositions (génère sandbox/skill_proposals,
    ne déploie pas vers les CLI).
  - app/forge_clawhub_bridge.py = install depuis ClawHub EXTERNE + SkillGuardian review.
  - tools/forge_rescue.py::_gemini_session_state = LIT ~/.gemini/skills pour diagnostic
    (ne synchronise pas).
  Aucun module ne MATÉRIALISE le registre canonical vers le dir local de chaque CLI.
  Ce module comble exactement ce trou : canonical (docs/skills/ + hub `skill list`)
  → dirs locaux de chaque CLI (.claude/skills, ~/.gemini/skills, copilot), format adapté
  par CLI, réversible via manifest. Réutilise docs/skills/ comme source (0 nouveau store).

CONTEXTE D'EXÉCUTION — IMPORTANT :
  Lit/écrit ~/.gemini, ~/.claude et le dir Copilot = profil user. La sandbox Nokido
  (LaForgeSbxOffline) reçoit Access Denied sur ces chemins (vérifié 2026-06-10). DONC :
  lancer EN SESSION user via le préfixe `!` du prompt :
      ! %USERPROFILE%/miniforge3/python.exe __import__("os").path.expanduser("~/Script python IA/LaForge/tools/forge_skill_sync.py") --discover
  PAS via le hub sandbox. (Option future : tâche onlogon silencieuse, cf
  memory schtasks_silent_onlogon_account_hide.)

MODES :
  --discover   read-only. Cartographie les dirs + formats + skills + erreurs de load
               de chaque CLI, + diff vs canonical. Sortie JSON. AUCUNE écriture.
  --plan       dry-run (DÉFAUT). Montre ce qui serait consolidé / déployé / écrasé / skippé.
  --apply      exécute : consolide les skills CLI-only → canonical, puis matérialise le
               canonical vers chaque CLI selon `targets`. Symlink par défaut, --copy sinon.
  --rollback   défait le dernier --apply via le manifest.

POLITIQUE `targets` :
  Chaque docs/skills/<slug>/SKILL.md peut déclarer dans son frontmatter :
      targets: [claude, gemini, copilot]
  Si absent → défaut = UNIVERSAL (les 3) SAUF si le slug est dans CLIENT_ONLY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum
from dataclasses import dataclass

# Racine importable AVANT le namespace : lance par chemin (prefixe `!`, cwd = superrepo),
# sys.path[0] = tools/ et `nokido_agent` (dossier de la racine) reste introuvable -- mesure
# 2026-09-26, `--preview` mourait ici. L'amorce plus bas (forge_skill_policy) venait trop tard.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402


class AssetType(str, Enum):
    SKILL = "skill"
    HOOK = "hook"
    WORKFLOW = "workflow"
    PLUGIN = "plugin"

@dataclass
class AssetConfig:
    canonical_dir: Path
    filename: str
    cli_dirs: dict

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "sandbox" / "skill_sync_manifest.json"
CONSOLIDATE_NOTE = "<!-- consolidé dans le canonical par forge_skill_sync (origine: {origin}) -->"

HOME = Path.home()

ASSET_REGISTRY = {
    AssetType.SKILL: AssetConfig(
        canonical_dir=ROOT / "docs" / "skills",
        filename="SKILL.md",
        cli_dirs={
            "claude": {"dir": HOME / ".claude" / "skills", "fmt": "skillmd"},
            "gemini": {"dir": HOME / ".gemini" / "skills", "fmt": "skillmd"},
            "copilot": {"dir": None, "fmt": "copilot"},  # résolu dynamiquement
        }
    ),
    AssetType.HOOK: AssetConfig(
        canonical_dir=ROOT / "tools" / "hooks",
        filename="hook.py",
        cli_dirs={
            "claude": {"dir": HOME / ".claude" / "hooks", "fmt": "python"},
            "gemini": {"dir": HOME / ".gemini" / "hooks", "fmt": "python"},
            "copilot": {"dir": None, "fmt": "python"},
        }
    ),
}

# Rétrocompatibilité temporaire (Phase A)
CANONICAL_DIR = ASSET_REGISTRY[AssetType.SKILL].canonical_dir
CLI_TARGETS = ASSET_REGISTRY[AssetType.SKILL].cli_dirs


# Dirs skills natifs par CLI. Copilot = candidats (détection à l'exécution, varie selon
# l'install). Le 1er existant gagne ; --discover rapporte lequel.
COPILOT_CANDIDATES = [
    HOME / ".copilot" / "skills",
    HOME / ".config" / "github-copilot" / "skills",
    HOME / "AppData" / "Roaming" / "github-copilot" / "skills",
    HOME / "AppData" / "Local" / "github-copilot" / "skills",
    HOME / "AppData" / "Roaming" / "GitHub Copilot CLI" / "skills",
    HOME / ".copilot" / "agents",
    HOME / ".config" / "github-copilot" / "agents",
]
# Racines où chercher en profondeur si aucun candidat plat ne matche (layout namespacé
# Copilot type personal-agents/<slug>/SKILL.md).
COPILOT_ROOTS = [
    HOME / ".copilot",
    HOME / ".config" / "github-copilot",
    HOME / "AppData" / "Roaming" / "github-copilot",
    HOME / "AppData" / "Local" / "github-copilot",
    HOME / "AppData" / "Roaming" / "GitHub Copilot CLI",
]

# CLI_TARGETS est géré via ASSET_REGISTRY[AssetType.SKILL].cli_dirs

# Skills volontairement liés à UN client (ne pas universaliser) — cf décision user
# 2026-06-10 "tout sauf client-only".
CLIENT_ONLY = {
    "forge-connectors": ["claude"],
    "forge-marketplace": ["claude"],
    "forge-models": ["gemini"],          # pools quota Gemini Flash/Pro/Preview
    "forge-core": ["gemini"],  # adaptation débit propre au runtime Gemini
}
# Préfixes client-only (familles de plugins).
CLIENT_ONLY_PREFIX = {
    "caveman": ["claude"],
    "document-skills": ["claude"],
}

# P1/P2 — moindre-privilège par ring. CLI_RING miroir de nokido_hub._AGENT_RING (ring BAS = PLUS
# de droits) : un CLI reçoit un skill si son ring <= min_ring (is_at_least). La POLITIQUE min_ring
# (map + résolution) = SOURCE UNIQUE dans forge_skill_policy (app/), partagée avec le hub
# (forge_mcp_registry.handle_skill). Fallback permissif si app/ injoignable (le sync tourne quand même).
CLI_RING = {"claude": 2, "gemini": 3, "copilot": 3}
try:
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_skill_policy import DEFAULT_MIN_RING, skill_min_ring as _shared_min_ring  # type: ignore
except Exception:
    DEFAULT_MIN_RING = 3

    def _shared_min_ring(slug, fm=None):
        return DEFAULT_MIN_RING

ALL_CLIS = ["claude", "gemini", "copilot"]


# ───────────────────────── frontmatter ─────────────────────────
def _parse_frontmatter(text: str) -> dict:
    """Parse le bloc YAML frontmatter `--- ... ---`. yaml si dispo, sinon parser maigre."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    # Fallback maigre : key: value + listes inline [a, b] et 'name'/'description'/'targets'.
    out: dict = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            out[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            out[key] = val.strip("'\"")
    return out


def _firewall_skill(slug: str, text: str) -> tuple:
    """Garde-fou ANTI-INJECTION-STOCKÉE (P3) : un SKILL.md = texte NON-FIABLE dont la description
    atterrit dans le system-context de CHAQUE agent. On passe description+corps au SemanticFirewall
    (detect_injection EN/FR). Fail-closed sur injection DÉTECTÉE. Dégrade (proceed + warn) si le
    module firewall est indisponible (defense-in-depth — ne doit pas briquer le sync)."""
    try:
        for p in (str(ROOT / "app"), str(ROOT / "tools")):
            if p not in sys.path:
                sys.path.insert(0, p)
        from nokido_agent.app.forge_semantic_firewall import get_firewall  # type: ignore

        fm = _parse_frontmatter(text)
        desc = str(fm.get("description", ""))
        body = text.split("\n---", 1)[-1] if text.startswith("---") else text
        pf = get_firewall().pre_flight(task=desc, context=body[:4000], ring=3, provider="local")
        if getattr(pf, "injection", False):
            return False, getattr(pf, "reason", "injection détectée")
        return True, "ok"
    except Exception as e:
        print(f"[firewall] INDISPONIBLE pour {slug} ({e}) -> déploiement DÉGRADÉ (non bloqué)", flush=True)
        return True, f"firewall indisponible: {e}"


def _native(slug: str) -> bool:
    """Skill LaForge-NATIF (décision user : "natifs nokido, PAS claude/externes").
    Seuls ces skills sont unifiés cross-CLI. Tout autre (skill-creator, smithery-ai-cli,
    document-skills*, caveman*, claude-*) = JAMAIS consolidé ni déployé par le sync."""
    return slug.startswith(("forge-", "nokido-")) or slug in {"forge-core", "netcfg-agent"}


def _min_ring_for(slug: str, fm: dict) -> int:
    """Ring minimal requis (politique partagée forge_skill_policy : frontmatter > map > défaut)."""
    return _shared_min_ring(slug, fm)


def _targets_for(slug: str, fm: dict) -> list[str]:
    """CLI cibles. 2 mondes SÉPARÉS (règle d'or Nokido) : la résolution sémantique des cibles
    (CLIENT_ONLY > NATIF > `targets`/UNIVERSAL) dit OÙ le skill VEUT aller ; PUIS la grille
    déterministe moindre-privilège filtre où il PEUT aller (ring CLI <= min_ring, is_at_least)."""
    if slug in CLIENT_ONLY:
        base = CLIENT_ONLY[slug]
    else:
        pref_hit = next((clis for pref, clis in CLIENT_ONLY_PREFIX.items() if slug.startswith(pref)), None)
        if pref_hit is not None:
            base = pref_hit
        elif not _native(slug):
            return []  # externe / Claude -> jamais unifié cross-CLI
        else:
            t = fm.get("targets")
            base = [x for x in t if x in ALL_CLIS] if (isinstance(t, list) and t) else list(ALL_CLIS)
    mr = _min_ring_for(slug, fm)
    return [c for c in base if CLI_RING.get(c, DEFAULT_MIN_RING) <= mr]


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _sha(p: Path) -> str:
    try:
        return _sha_bytes(p.read_bytes())
    except Exception:
        return ""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────── lecture d'un dir de skills ─────────────────────────
def _read_skill_dir(d: Path | None) -> dict:
    """Cartographie un dir <root>/<slug>/SKILL.md. Robuste : dir absent / accès refusé."""
    info: dict = {"dir": str(d) if d else None, "exists": False, "readable": True, "skills": {}, "errors": []}
    if not d:
        return info
    try:
        if not d.exists():
            return info
        info["exists"] = True
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            sk = sub / "SKILL.md"
            entry = {"has_skill_md": sk.exists(), "name": None, "description": None, "fm_keys": [], "sha": None}
            if sk.exists():
                try:
                    txt = sk.read_text(encoding="utf-8", errors="replace")
                    fm = _parse_frontmatter(txt)
                    entry["name"] = fm.get("name")
                    entry["description"] = (fm.get("description") or "")[:120]
                    entry["fm_keys"] = sorted(fm.keys())
                    entry["sha"] = _sha(sk)
                    # heuristique "load fail" : frontmatter manquant ou name absent
                    if not fm or not fm.get("name"):
                        info["errors"].append(f"{sub.name}: frontmatter/name manquant (load-fail probable)")
                except Exception as e:
                    info["errors"].append(f"{sub.name}: lecture SKILL.md KO — {e}")
            else:
                info["errors"].append(f"{sub.name}: pas de SKILL.md")
            info["skills"][sub.name] = entry
    except PermissionError as e:
        info["readable"] = False
        info["errors"].append(f"ACCESS DENIED ({e}) — lancer en session user (préfixe ! du prompt)")
    except Exception as e:
        info["errors"].append(f"scan KO — {e}")
    return info


def _hunt_copilot_dir() -> dict:
    """Cherche en profondeur où Copilot range ses skills (dir <slug>/SKILL.md).

    Copilot expose des namespaces (personal-agents, builtin) → layout potentiellement
    <root>/<namespace>/<slug>/SKILL.md. On remonte au parent du parent du 1er SKILL.md
    trouvé comme racine 'skills' présumée. Évidence retournée pour validation humaine.
    """
    evidence: list = []
    for root in COPILOT_ROOTS:
        try:
            if not root.exists():
                continue
            for sk in root.rglob("SKILL.md"):
                evidence.append(str(sk))
                if len(evidence) >= 20:
                    break
        except Exception:
            continue
    skills_root = str(Path(evidence[0]).parent.parent) if evidence else None
    return {"skills_root": skills_root, "skill_md_found": evidence}


def _resolve_copilot_dir() -> Path | None:
    # Copilot CLI (doc officielle 2026) : skills perso = ~/.copilot/skills/<slug>/SKILL.md
    # (MÊME format SKILL.md que claude/gemini ; dir créé on-demand → retourné dès que
    # ~/.copilot existe). COPILOT_HOME override le chemin de base.
    copilot_home = Path(os.environ.get("COPILOT_HOME", str(HOME / ".copilot")))
    try:
        if copilot_home.exists():
            return copilot_home / "skills"
    except Exception:
        pass
    for c in COPILOT_CANDIDATES:
        try:
            if c.exists():
                return c
        except Exception:
            continue
    h = _hunt_copilot_dir()
    if h.get("skills_root"):
        return Path(h["skills_root"])
    return None


def _canonical_index() -> dict:
    """Skills canonical = docs/skills/<slug>/SKILL.md + targets résolus."""
    idx: dict = {}
    if not CANONICAL_DIR.exists():
        return idx
    for sub in sorted(CANONICAL_DIR.iterdir()):
        sk = sub / "SKILL.md"
        if not sub.is_dir() or not sk.exists():
            continue
        fm = _parse_frontmatter(sk.read_text(encoding="utf-8", errors="replace"))
        idx[sub.name] = {
            "path": str(sk),
            "name": fm.get("name") or sub.name,
            "targets": _targets_for(sub.name, fm),
            "sha": _sha(sk),
        }
    return idx


# ───────────────────────── DISCOVER ─────────────────────────
def discover() -> dict:
    CLI_TARGETS["copilot"]["dir"] = _resolve_copilot_dir()
    report = {
        "ts": _now(),
        "home": str(HOME),
        "canonical_dir": str(CANONICAL_DIR),
        "canonical": _canonical_index(),
        "clis": {},
        "copilot_candidates": [str(c) for c in COPILOT_CANDIDATES],
    }
    for cli, spec in CLI_TARGETS.items():
        report["clis"][cli] = _read_skill_dir(spec["dir"])
    # Diff : skills présents dans un CLI mais ABSENTS du canonical (à consolider).
    canon = set(report["canonical"].keys())
    cli_only: dict = {}
    for cli, data in report["clis"].items():
        extra = [s for s in data.get("skills", {}) if s not in canon]
        if extra:
            cli_only[cli] = extra
    report["cli_only_to_consolidate"] = cli_only
    # Manque : skills canonical pas (encore) déployés là où targets le demande.
    missing: dict = {c: [] for c in ALL_CLIS}
    for slug, meta in report["canonical"].items():
        for cli in meta["targets"]:
            have = report["clis"].get(cli, {}).get("skills", {})
            if slug not in have:
                missing[cli].append(slug)
    report["missing_per_cli"] = missing
    report["copilot_hunt"] = _hunt_copilot_dir()
    return report


# ───────────────────────── PLAN / APPLY ─────────────────────────
def _adapt_content(slug: str, src_text: str, cli: str) -> str:
    """Adapte un SKILL.md canonical au format du CLI cible.

    claude/gemini : format SKILL.md identique (YAML frontmatter name+description) → passthrough.
    copilot       : Copilot CLI attend aussi un SKILL.md frontmatter ; on garantit la présence
                    des clés minimales et on retire les clés non reconnues qui font 'Failed to
                    load' (heuristique : on ne garde que name/description/+ body). Affiné après
                    --discover sur un skill Copilot fonctionnel.
    """
    if cli in ("claude", "gemini", "copilot"):
        return src_text
    # copilot : normalise le frontmatter aux clés sûres.
    fm = _parse_frontmatter(src_text)
    name = fm.get("name") or slug
    desc = (fm.get("description") or "").replace("\n", " ").strip()
    body = src_text
    if src_text.startswith("---"):
        end = src_text.find("\n---", 3)
        if end != -1:
            body = src_text[end + 4 :].lstrip("\n")
    safe_fm = f"---\nname: {name}\ndescription: {desc}\n---\n\n"
    return safe_fm + body


def _sanitize_fm(text: str) -> str:
    """Frontmatter YAML-safe pour parsers STRICTS (Copilot / .agents).

    1. Retire les clés INTERNES Nokido (`targets`) — métadonnée du sync, rejetée.
    2. Met entre guillemets toute valeur scalaire contenant ':' ou '#' non quotée
       (sinon 'failed to parse yaml: mapping value' — ex: 'description: Triggers : ...').
    Listes [..], blocs |/>, ancres, valeurs déjà quotées = laissés intacts.
    """
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    head, body = text[:end], text[end:]
    INTERNAL = {"targets", "min_ring", "caps"}  # métadonnées sync/policy : jamais déployées au CLI
    lines = head.splitlines()
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        if ":" not in ln:
            out.append(ln)  # '---', lignes vides
            i += 1
            continue
        key = ln.split(":", 1)[0].strip()
        val = ln.split(":", 1)[1].strip()
        # Bloc scalaire (folded > / literal |) : les lignes INDENTÉES suivantes = la valeur,
        # PAS des key:value. Parsers stricts OK avec '>' mais le line-by-line les manglait ->
        # on replie le bloc en UNE ligne quotée (max compat).
        if val in (">", "|", ">-", "|-", ">+", "|+", ">2", "|2"):
            block, j = [], i + 1
            while j < n and (lines[j].strip() == "" or lines[j][:1] in (" ", "\t")):
                block.append(lines[j].strip())
                j += 1
            if key not in INTERNAL:
                folded = " ".join(b for b in block if b)
                esc = folded.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'{key}: "{esc}"')
            i = j
            continue
        if key in INTERNAL:
            i += 1
            continue
        if val and val[0] not in "[{\"'|>&*#" and (":" in val or "#" in val):
            esc = val.replace("\\", "\\\\").replace('"', '\\"')
            out.append(f'{key}: "{esc}"')
        else:
            out.append(ln)
        i += 1
    return "\n".join(out) + body


def _deploy_one(slug: str, src: Path, dest_dir: Path, cli: str, copy: bool, manifest_actions: list) -> dict:
    dest_skill_dir = dest_dir / slug
    dest = dest_skill_dir / "SKILL.md"
    prev_sha = _sha(dest) if dest.exists() else None
    src_text = src.read_text(encoding="utf-8", errors="replace")
    cleaned = _sanitize_fm(src_text)  # YAML-safe (strip targets + quote colons) pour parsers stricts
    needs_transform = cleaned != src_text
    dest_skill_dir.mkdir(parents=True, exist_ok=True)
    mode = "copy"
    # Symlink (exact, auto-propage) UNIQUEMENT si aucune transform ; sinon copie nettoyée (LF).
    if not copy and not needs_transform:
        try:
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            os.symlink(src, dest)
            mode = "symlink"
        except Exception:
            dest.write_bytes(cleaned.encode("utf-8"))
            mode = "copy"
    else:
        dest.write_bytes(cleaned.encode("utf-8"))
    manifest_actions.append(
        {"cli": cli, "slug": slug, "dest": str(dest), "mode": mode, "prev_sha": prev_sha}
    )
    return {"cli": cli, "slug": slug, "mode": mode, "replaced": prev_sha is not None}


def _cli_only_sources() -> dict:
    """slugs présents dans un dir CLI mais ABSENTS du canonical → {slug: Path(SKILL.md)}.

    Dedup : 1er CLI qui porte le slug gagne (les copies inter-CLI sont censées être
    le même skill). Permet de compléter le canonical avec les skills nés côté CLI.
    """
    CLI_TARGETS["copilot"]["dir"] = _resolve_copilot_dir()
    canon = set(_canonical_index().keys())
    out: dict = {}
    for cli, spec in CLI_TARGETS.items():
        d = spec["dir"]
        if not d:
            continue
        try:
            if not d.exists():
                continue
            for sub in sorted(d.iterdir()):
                sk = sub / "SKILL.md"
                if sub.is_dir() and sk.exists() and sub.name not in canon and sub.name not in out:
                    out[sub.name] = sk
        except Exception:
            continue
    return out


def consolidate(apply: bool, manifest_actions: list) -> list:
    """Copie les skills CLI-only dans le canonical docs/skills/<slug>/SKILL.md.

    Ne touche JAMAIS un slug canonical existant (idempotent). Le contenu source = la
    version CLI telle quelle (frontmatter name+description) ; targets résolus à la lecture
    via la politique CLIENT_ONLY/UNIVERSAL. Traçé au manifest pour rollback.
    """
    preview = []
    for slug, src in _cli_only_sources().items():
        if not _native(slug):
            continue  # n'aspire PAS les skills externes/Claude dans le canonical Nokido
        dest = CANONICAL_DIR / slug / "SKILL.md"
        if dest.exists():
            continue
        fm = _parse_frontmatter(src.read_text(encoding="utf-8", errors="replace"))
        preview.append({"slug": slug, "src": str(src), "dest": str(dest), "targets": _targets_for(slug, fm)})
        if apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())  # octets exacts : pas de traduction newline (sha stable)
            manifest_actions.append(
                {"cli": "canonical", "slug": slug, "dest": str(dest), "mode": "consolidate", "prev_sha": None}
            )
    return preview


def _cli_dirs(cli: str) -> list:
    """UN dir par CLI. NE PAS déployer dans ~/.agents/skills (partagé Gemini+Copilot) :
    ça créerait des DOUBLONS (chaque CLI lit son dir propre + ~/.agents = 'skill conflict').
    Chaque CLI lit son dir propre ; ~/.agents = à garder propre (nettoyage manuel des dups)."""
    d = CLI_TARGETS.get(cli, {}).get("dir")
    return [d] if d else []


def _token_budget(canon: dict) -> dict:
    """P4 — poids-token du set de skills PAR CLI (taxe de contexte : les descriptions restent
    chargées en permanence pour le triggering). count_tokens (forge_tokenizer, approx tiktoken).
    Gauge + warn si > LAFORGE_SKILL_TOKEN_BUDGET. Ne DROP rien (silencieux = mauvais) : on signale,
    l'opérateur arbitre (min_ring pour restreindre, ou accepte)."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_tokenizer import count_tokens  # type: ignore
    except Exception:
        def count_tokens(t, provider="openai", **k):
            return max(1, len(t) // 4)  # fallback ~4 char/token
    cap = int(get_secret("LAFORGE_SKILL_TOKEN_BUDGET") or "6000")
    budget = {c: {"skills": 0, "tokens": 0} for c in ALL_CLIS}
    for slug, meta in canon.items():
        try:
            fm = _parse_frontmatter(Path(meta["path"]).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            fm = {}
        toks = count_tokens(str(fm.get("description", "")), provider="openai")
        for cli in meta["targets"]:
            if cli in budget:
                budget[cli]["skills"] += 1
                budget[cli]["tokens"] += toks
    for c in budget:
        budget[c]["over_budget"] = budget[c]["tokens"] > cap
    budget["_cap"] = cap
    return budget


def plan_or_apply(apply: bool, copy: bool, overwrite: bool = False, firewall: bool = True) -> dict:
    CLI_TARGETS["copilot"]["dir"] = _resolve_copilot_dir()
    manifest_actions: list = []
    skipped: list = []
    firewall_blocked: list = []

    # Étape 1 — consolidation : skills CLI-only → canonical docs/skills/.
    consolidated = consolidate(apply, manifest_actions)

    # Étape 2 — index canonical. En --apply il contient déjà les consolidés (écrits) ;
    # en --plan on les ajoute virtuellement (source = dir CLI) pour prévisualiser le déploiement.
    canon = _canonical_index()
    if not apply:
        for c in consolidated:
            slug = c["slug"]
            if slug not in canon:
                src_p = Path(c["src"])
                fm = _parse_frontmatter(src_p.read_text(encoding="utf-8", errors="replace"))
                canon[slug] = {
                    "path": str(src_p),
                    "name": fm.get("name") or slug,
                    "targets": _targets_for(slug, fm),
                    "sha": _sha(src_p),
                }

    # Étape 3 — déploiement canonical → chaque CLI selon targets.
    actions_preview: list = []
    for slug, meta in canon.items():
        src = Path(meta["path"])
        if firewall:
            fok, freason = _firewall_skill(slug, src.read_text(encoding="utf-8", errors="replace"))
            if not fok:
                skipped.append({"slug": slug, "why": f"BLOQUÉ firewall (injection stockée): {freason}"})
                firewall_blocked.append({"slug": slug, "reason": freason})
                continue  # fail-closed : ne déploie sur AUCUN CLI
        for cli in meta["targets"]:
            dirs = _cli_dirs(cli)
            if not dirs:
                skipped.append({"cli": cli, "slug": slug, "why": "dir CLI introuvable (copilot non localisé)"})
                continue
            # Cible = contenu NETTOYÉ (YAML-safe) -> on compare à ça, pas au canonical brut.
            try:
                target_sha = _sha_bytes(_sanitize_fm(src.read_text(encoding="utf-8", errors="replace")).encode("utf-8"))
            except Exception:
                target_sha = meta["sha"]
            for dest_dir in dirs:
                dest = dest_dir / slug / "SKILL.md"
                dsha = _sha(dest) if dest.exists() else None
                if dsha == target_sha:
                    skipped.append({"cli": cli, "slug": slug, "why": "déjà identique"})
                    continue
                if dsha is None:
                    act = "CREATE"
                elif dsha == meta["sha"]:
                    # ancien déploiement non-nettoyé (notre stale) -> re-nettoyage, PAS un conflit.
                    act = "REPLACE"
                else:
                    act = "REPLACE"
                    if not overwrite:
                        skipped.append(
                            {"cli": cli, "slug": slug, "dir": str(dest_dir), "why": "conflit canonical≠local — --overwrite pour forcer"}
                        )
                        continue
                actions_preview.append({"cli": cli, "slug": slug, "action": act, "dest": str(dest)})
                if apply:
                    try:
                        _deploy_one(slug, src, dest_dir, cli, copy, manifest_actions)
                    except Exception as e:
                        skipped.append({"cli": cli, "slug": slug, "why": f"deploy KO — {e}"})

    result = {
        "ts": _now(),
        "mode": "apply" if apply else "plan",
        "consolidated": consolidated,
        "planned": actions_preview,
        "skipped": skipped,
        "firewall_blocked": firewall_blocked,
        "token_budget": _token_budget(canon),
        "copilot_dir": str(CLI_TARGETS["copilot"]["dir"]) if CLI_TARGETS["copilot"]["dir"] else None,
    }
    if apply:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        prev = []
        if MANIFEST.exists():
            try:
                prev = json.loads(MANIFEST.read_text(encoding="utf-8")).get("history", [])
            except Exception:
                prev = []
        prev.append({"ts": _now(), "actions": manifest_actions})
        MANIFEST.write_text(json.dumps({"history": prev}, indent=2, ensure_ascii=False), encoding="utf-8")
        result["applied"] = len(manifest_actions)
        result["manifest"] = str(MANIFEST)
    return result


def rollback() -> dict:
    if not MANIFEST.exists():
        return {"ok": False, "why": "pas de manifest"}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    history = data.get("history", [])
    if not history:
        return {"ok": False, "why": "manifest vide"}
    last = history.pop()
    undone = []
    for a in last.get("actions", []):
        dest = Path(a["dest"])
        try:
            if a["prev_sha"] is None:
                # création → supprimer + nettoyer le dir slug si vide
                if dest.exists() or dest.is_symlink():
                    dest.unlink()
                try:
                    dest.parent.rmdir()
                except OSError:
                    pass
                undone.append({"slug": a["slug"], "cli": a["cli"], "op": "removed"})
            else:
                # remplacement : on ne peut pas restaurer le contenu exact (pas stocké) —
                # on signale pour ré-apply manuel. (v2 : stocker le blob précédent.)
                undone.append({"slug": a["slug"], "cli": a["cli"], "op": "was-replace (contenu précédent non stocké)"})
        except Exception as e:
            undone.append({"slug": a["slug"], "cli": a["cli"], "op": f"KO {e}"})
    MANIFEST.write_text(json.dumps({"history": history}, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "undone": undone}


def diff_conflicts() -> dict:
    """Diff unifié des conflits canonical≠local (claude/gemini). splitlines() neutralise
    le CRLF → seul un contenu RÉELLEMENT différent ressort (les 6 fantômes = diff vide)."""
    import difflib

    CLI_TARGETS["copilot"]["dir"] = _resolve_copilot_dir()
    canon = _canonical_index()
    out: dict = {}
    for slug, meta in canon.items():
        for cli in meta["targets"]:
            dd = CLI_TARGETS[cli]["dir"]
            if not dd or cli not in ("claude", "gemini", "copilot"):
                continue
            dest = dd / slug / "SKILL.md"
            if not dest.exists() or _sha(dest) == meta["sha"]:
                continue
            canon_lines = Path(meta["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
            cli_lines = dest.read_text(encoding="utf-8", errors="replace").splitlines()
            d = list(
                difflib.unified_diff(
                    cli_lines, canon_lines, fromfile=f"{cli}/{slug} (local)", tofile=f"canonical/{slug}", lineterm=""
                )
            )
            if d:  # contenu réellement divergent (CRLF-only → splitlines l'annule → vide → exclu)
                out[f"{cli}/{slug}"] = {"diff_lines": len(d), "diff": d}
    return {"conflicts": out, "note": "absent ici => seul le CRLF différait (contenu identique)"}


def prune(apply: bool) -> dict:
    """Moindre-privilège (P1) — retire d'un dir CLI les skills canonical qui n'y sont PLUS
    autorisés (ring/targets). Ne touche QUE les slugs présents au canonical (jamais les skills
    propres du CLI). Idempotent : l'état déployé = exactement le set autorisé par la grille."""
    CLI_TARGETS["copilot"]["dir"] = _resolve_copilot_dir()
    canon = _canonical_index()
    removed: list = []
    for cli in ALL_CLIS:
        for dest_dir in _cli_dirs(cli):
            if not dest_dir or not dest_dir.exists():
                continue
            for sub in sorted(dest_dir.iterdir()):
                slug = sub.name
                if slug not in canon or cli in canon[slug]["targets"]:
                    continue  # inconnu au canonical (skill propre du CLI) OU autorisé -> garder
                rec = {"cli": cli, "slug": slug, "dir": str(dest_dir)}
                removed.append(rec)
                if apply:
                    try:
                        sk = sub / "SKILL.md"
                        if sk.exists():
                            sk.unlink()
                        if sub.is_dir() and not any(sub.iterdir()):
                            sub.rmdir()
                    except Exception as e:
                        rec["error"] = str(e)
    return {"mode": "prune" if apply else "prune-dry", "removed": removed}


# ── C1 phase A : asset HOOK — intelligence read-only ─────────────────────────
# Réalité terrain (vérifiée 2026-06-12) : un hook Claude Code n'est PAS un fichier
# déposé dans un dir façon skill, mais une COMMANDE déclarée dans settings.json
# (bloc "hooks" : event -> [{matcher, hooks:[{type:command, command}]}]). Le
# canonical = les scripts tools/*.py de Nokido (déjà en place, référencés par
# chemin absolu). "Centraliser" un hook = aligner les références settings de
# chaque CLI, PAS copier un fichier. discover_hooks rend cette vérité — ZÉRO
# mutation. L'apply (injection settings = gate d'orchestration) est la phase B.
# Corrige l'hypothèse "~/.claude/hooks dir" du registre : cf design doc C1.
_HOOK_SETTINGS = {
    "claude": [
        ROOT / ".claude" / "settings.local.json",
        ROOT / ".claude" / "settings.json",
        HOME / ".claude" / "settings.local.json",
        HOME / ".claude" / "settings.json",
    ],
    "gemini": [
        HOME / ".gemini" / "settings.json",
        ROOT / ".gemini" / "settings.json",
    ],
}


def _nokido_hook_scripts() -> dict:
    """Scripts hook canonical de Nokido = tools/hook_*.py + gardes nommés
    (bash_guard, session_anchor). Source de vérité du gate d'orchestration."""
    tools = ROOT / "tools"
    names = sorted(
        {p.name for p in tools.glob("hook_*.py")}
        | {n for n in ("bash_guard.py", "session_anchor.py") if (tools / n).exists()}
    )
    return {n: {"path": str(tools / n), "sha": _sha(tools / n)} for n in names}


def _extract_hook_refs(settings_path: Path) -> dict:
    """Hooks déclarés dans le settings d'un CLI : {event: [{matcher, script, command}]}.
    Robuste : fichier absent / JSON cassé / accès refusé -> erreur rapportée, pas d'exception."""
    out: dict = {"path": str(settings_path), "exists": False, "events": {}, "errors": []}
    try:
        if not settings_path.exists():
            return out
        out["exists"] = True
        data = json.loads(settings_path.read_text(encoding="utf-8", errors="replace"))
    except PermissionError as e:
        out["errors"].append(f"ACCESS DENIED ({e})")
        return out
    except Exception as e:  # JSON invalide, etc.
        out["errors"].append(f"JSON KO — {e}")
        return out
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        refs = []
        for g in groups:
            matcher = g.get("matcher", "") if isinstance(g, dict) else ""
            for h in ((g.get("hooks") or []) if isinstance(g, dict) else []):
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                # script = dernier .py, cherché dans command ET args (forme Gemini)
                refs.append({"matcher": matcher,
                             "script": _hook_script_name(h) if isinstance(h, dict) else None,
                             "command": cmd[:200]})
        if refs:
            out["events"][event] = refs
    return out


def discover_hooks() -> dict:
    """Carto read-only des hooks d'orchestration : scripts Nokido canonical vs ce que
    chaque CLI référence dans son settings. Révèle le gap (canonical pas câblé / référence
    orpheline). ZÉRO mutation. Alimente --asset hook (C1 phase A)."""
    canonical = _nokido_hook_scripts()
    report = {"ts": _now(), "asset_type": "hook", "canonical_scripts": canonical, "clis": {}}
    wired_all: set = set()
    for cli, paths in _HOOK_SETTINGS.items():
        per_file = [_extract_hook_refs(p) for p in paths]
        report["clis"][cli] = per_file
        for f in per_file:
            for refs in f.get("events", {}).values():
                for r in refs:
                    if r.get("script"):
                        wired_all.add(r["script"])
    canon_names = set(canonical.keys())
    report["wired_scripts"] = sorted(wired_all)
    report["canonical_not_wired"] = sorted(canon_names - wired_all)   # existe mais aucun CLI ne l'appelle
    report["wired_not_canonical"] = sorted(wired_all - canon_names)   # référencé mais pas un hook_*/guard connu
    return report


# ── C1 phase B : injection settings (gate d'orchestration) ───────────────────
# DESIRED_HOOKS = état-cible : quel script canonical sur quel (event, matcher).
# sync_hooks n'AJOUTE que ce qui manque (idempotent, jamais de doublon), backup
# .bak AVANT write. apply=False (défaut) = dry-run : montre le plan, ZÉRO écriture.
# MUTATION de settings vivants -> apply réservé GO user + EN SESSION user
# (HOME pour les settings globaux). cf docs/C1_DESIGN_CENTRALISATION_ASSETS.md.
_LAFORGE_PY = os.environ.get("LAFORGE_PYTHON", __import__("os").path.expanduser(r"~/miniforge3/python.exe"))

DESIRED_HOOKS = {
    "claude": [
        ("PreToolUse", "Bash", "bash_guard.py"),
        ("PreToolUse", "Bash", "hook_bash_compact.py"),
        ("PreToolUse", "PowerShell", "bash_guard.py"),
        ("PreToolUse", "Read|Grep|Glob", "hook_search_guard.py"),
        ("PreToolUse", "Edit|Write", "hook_pretool_guard.py"),
        ("PreToolUse", "*", "hook_gate_orchestrator.py"),
        ("PostToolUse", "Write|Edit", "hook_posttool_validate.py"),
        ("Stop", "", "session_anchor.py"),
    ],
    "gemini": [
        ("AfterModel", "*", "hook_gate_orchestrator.py"),
    ],
}


def _hook_command(script: str, cli: str = "claude"):
    """Commande hook adaptée au CLI. Claude Code = string shell `"py" "script"`
    (spawn direct, accepte l'exe quoté). Gemini CLI exécute le hook via PowerShell
    et EXIGE {command, args} SÉPARÉS : une string `"exe" "script"` casse en
    ParserError (exe quoté sans call-operator `&`). cf bug Gemini OAuth 2026-06-14."""
    py = _LAFORGE_PY
    path = str(ROOT / "tools" / script)
    if cli == "gemini":
        return {"command": py, "args": [path]}
    return f'"{py}" "{path}"'


def _hook_script_name(h: dict) -> str | None:
    """Nom du .py d'un hook, qu'il soit dans `command` (forme string Claude) ou
    dans `args` (forme structurée Gemini). Idempotence args-aware."""
    blob = (h.get("command", "") or "") + " " + " ".join(h.get("args", []) or [])
    py = re.findall(r"[\w./\\-]+\.py", blob)
    return Path(py[-1]).name if py else None


def _primary_settings(cli: str) -> Path | None:
    """Settings cible d'un CLI : 1er existant (projet prioritaire) sinon 1er chemin."""
    paths = _HOOK_SETTINGS.get(cli, [])
    for p in paths:
        if p.exists():
            return p
    return paths[0] if paths else None


def _cmd_script(command: str) -> str | None:
    """Nom du script .py référencé par une commande hook (dernier .py),
    séparateur/quote/chemin-python INDIFFÉRENTS. Pour comparaison idempotente."""
    py = re.findall(r"[\w./\\-]+\.py", command or "")
    return Path(py[-1]).name if py else None


def _ensure_hook(hooks: dict, event: str, matcher: str, script: str, command: str) -> bool:
    """Ajoute (event,matcher,script) si absent. True si modif. Idempotence par NOM de
    script (un bash_guard.py déjà câblé en '/' n'est pas re-injecté en '\\')."""
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        return False
    grp = next((g for g in groups if isinstance(g, dict) and g.get("matcher", "") == matcher), None)
    if grp is None:
        grp = {"matcher": matcher, "hooks": []}
        groups.append(grp)
    cmds = grp.setdefault("hooks", [])
    if any(isinstance(h, dict) and _hook_script_name(h) == script for h in cmds):
        return False  # même script déjà câblé -> ne pas dupliquer (forme/séparateur indifférents)
    if isinstance(command, dict):   # forme structurée Gemini {command, args}
        cmds.append({"type": "command", **command})
    else:                           # forme string Claude
        cmds.append({"type": "command", "command": command})
    return True


def sync_hooks(apply: bool = False) -> dict:
    """Injecte les hooks DESIRED manquants dans le settings de chaque CLI (idempotent,
    backup .bak avant write). apply=False (DÉFAUT) = dry-run, ZÉRO écriture. MUTATION de
    config vivante -> apply = GO user + EN user. Le gate d'orchestration vit ici."""
    import copy

    plan = {"ts": _now(), "asset_type": "hook", "mode": "apply" if apply else "dry-run", "clis": {}}
    for cli, desired in DESIRED_HOOKS.items():
        target = _primary_settings(cli)
        rec = {"target": str(target) if target else None, "added": [], "skipped": [],
               "errors": [], "written": False, "changed": False}
        if not target:
            rec["errors"].append("aucun settings cible")
            plan["clis"][cli] = rec
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8", errors="replace")) if target.exists() else {}
        except PermissionError as e:
            rec["errors"].append(f"ACCESS DENIED ({e}) — lancer EN user")
            plan["clis"][cli] = rec
            continue
        except Exception as e:  # JSON cassé
            rec["errors"].append(f"JSON KO — {e}")
            plan["clis"][cli] = rec
            continue
        if not isinstance(data, dict):
            rec["errors"].append("settings racine non-objet")
            plan["clis"][cli] = rec
            continue
        before = copy.deepcopy(data)
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            rec["errors"].append("bloc hooks non-objet — abstention")
            plan["clis"][cli] = rec
            continue
        # Gap-aware anti-double-fire : un (event, script) déjà câblé dans N'IMPORTE
        # quel settings de ce CLI (global OU projet) ne sera PAS ré-injecté — Claude
        # Code fusionne global+projet, sinon le hook tournerait 2×.
        already = set()
        for p in _HOOK_SETTINGS.get(cli, []):
            for ev, rlist in _extract_hook_refs(p).get("events", {}).items():
                for r in rlist:
                    if r.get("script"):
                        already.add((ev, r["script"]))
        for event, matcher, script in desired:
            if not (ROOT / "tools" / script).exists():
                rec["errors"].append(f"canonical absent: {script}")
                continue
            if (event, script) in already:
                rec["skipped"].append({"event": event, "matcher": matcher, "script": script,
                                       "reason": "déjà câblé (global/projet) — anti-double-fire"})
                continue
            entry = {"event": event, "matcher": matcher, "script": script}
            (rec["added"] if _ensure_hook(hooks, event, matcher, script, _hook_command(script, cli)) else rec["skipped"]).append(entry)
        rec["changed"] = data != before
        if rec["changed"] and apply:
            try:
                bak = target.with_suffix(target.suffix + ".bak")
                bak.write_text(json.dumps(before, indent=2, ensure_ascii=False), encoding="utf-8")
                target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                rec["written"] = True
                rec["backup"] = str(bak)
            except Exception as e:
                rec["errors"].append(f"write KO — {e}")
        plan["clis"][cli] = rec
    return plan


def main() -> int:
    # Console de l'owner (prefixe `!`) : cp1252. `--preview` y mourait en UnicodeEncodeError
    # sur le « ≠ » du rapport, apres avoir tout calcule (mesure 2026-09-26). Avant argparse :
    # l'aide porte le meme caractere.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — muet-ok : sortie non reconfigurable
        pass
    ap = argparse.ArgumentParser(description="Matérialiseur de skills cross-CLI souverain (Nokido)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--discover", action="store_true", help="read-only : carto dirs+formats+diff")
    g.add_argument("--preview", action="store_true", help="dry-run : montre consolidation+déploiement (DÉFAUT)")
    g.add_argument("--plan", action="store_true", help="alias de --preview (dry-run)")
    g.add_argument("--apply", action="store_true", help="exécute le déploiement")
    g.add_argument("--rollback", action="store_true", help="défait le dernier --apply")
    g.add_argument("--diff", action="store_true", help="affiche le diff unifié des conflits canonical≠local")
    g.add_argument("--prune", action="store_true", help="moindre-privilège : retire des CLI les skills canonical déautorisés (ring/targets)")
    g.add_argument("--prune-dry", action="store_true", help="prune en dry-run (montre ce qui serait retiré)")
    ap.add_argument("--copy", action="store_true", help="copie au lieu de symlink")
    ap.add_argument("--overwrite", action="store_true", help="autorise REPLACE (canonical écrase un skill CLI divergent)")
    ap.add_argument("--no-firewall", action="store_true", help="désactive le garde-fou anti-injection au sync (NON recommandé)")
    ap.add_argument("--asset", choices=["skill", "hook", "all"], default="skill",
                    help="type d'asset (défaut skill ; hook = discover read-only C1 phase A ; all = skills+hooks)")
    args = ap.parse_args()

    # ── C1 : aiguillage par type d'asset. asset=skill (défaut) garde 100% du
    # comportement existant. asset=hook : --discover=carto read-only, --apply=injection
    # settings (MUTATION, GO user + EN user), défaut/--preview=dry-run injection.
    if args.asset in ("hook", "all"):
        if args.asset == "all":
            out = {"skills": discover(), "hooks": discover_hooks()}
        elif args.discover:
            out = discover_hooks()
        elif args.apply:
            out = sync_hooks(apply=True)
        else:  # preview/plan (défaut) : montre l'injection SANS rien écrire
            out = sync_hooks(apply=False)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.discover:
        out = discover()
    elif args.apply:
        out = plan_or_apply(apply=True, copy=args.copy, overwrite=args.overwrite, firewall=not args.no_firewall)
    elif args.rollback:
        out = rollback()
    elif args.diff:
        out = diff_conflicts()
    elif args.prune:
        out = prune(apply=True)
    elif args.prune_dry:
        out = prune(apply=False)
    else:
        out = plan_or_apply(apply=False, copy=args.copy, overwrite=args.overwrite, firewall=not args.no_firewall)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
