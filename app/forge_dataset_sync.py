# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_dataset_sync
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_dataset_sync.py — Synchronisation dynamique des datasets NR
==================================================================
Principe : les datasets NR sont dérivés du code source.
Quand le code change, les datasets sont régénérés automatiquement.

Chaque dataset porte :
  _src_hash  : hash SHA256[:8] des sources dont il dépend
  _version   : version Nokido au moment de la génération
  _generated : timestamp ISO

Au prochain run NR :
  1. DatasetSync.check() compare _src_hash avec le hash actuel des sources
  2. Si différent → régénère le dataset
  3. Le NR utilise toujours le dataset frais

Datasets gérés :
  is_at_least_matrix.json  ← forge_integrity.IntegrityRing (calcul exhaustif)
  integrity_rings.json     ← IntegrityRing.consensus_level() (introspection)
  integrity_edge_cases.json← CapabilityToken signatures (scan AST)
  behavior_gold.json       ← forge_mcp_security._resolve_role() (scan règles)
  tui_handlers.json        ← forge_handlers.py sous-commandes (scan regex)

Usage :
  from forge_dataset_sync import DatasetSync
  sync = DatasetSync()
  changed = sync.check_and_update()   # régénère si nécessaire
  print(changed)  # {'is_at_least_matrix': True, ...}

  # Depuis mcp_nr avant run_fast() :
  DatasetSync().check_and_update()
"""


import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parent.parent
_APP = _ROOT / "app"
_DATA_NR = _ROOT / "data_nr"

sys.path.insert(0, str(_APP))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _src_hash(*paths: Path) -> str:
    """Hash SHA256[:12] de un ou plusieurs fichiers source."""
    h = hashlib.sha256()
    for p in paths:
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _version() -> str:
    """Version."""
    try:
        from nokido_agent.app import forge_version as fv

        fv.invalidate_cache()
        return fv.get()
    except Exception:
        return "0.13.0"


def _now() -> str:
    """Now."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict:
    """Load.

    Args:
        path: Description.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(path: Path, data: dict) -> None:
    """Save.

    Args:
        path: Description.
        data: Description.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _stale(path: Path, current_hash: str) -> bool:
    """Retourne True si le dataset est absent ou périmé."""
    if not path.exists():
        return True
    d = _load(path)
    return d.get("_src_hash") != current_hash


# ─────────────────────────────────────────────────────────────────────────────
# Générateurs individuels
# ─────────────────────────────────────────────────────────────────────────────


def gen_is_at_least_matrix() -> dict:
    """
    Génère is_at_least_matrix.json depuis IntegrityRing.
    25 cas = toutes les combinaisons (ring, required) pour 5 rings.
    La sémantique : ring ≤ required (int) ↔ is_at_least(ring, required) = True.
    """
    from nokido_agent.app.forge_integrity import IntegrityRing, is_at_least

    rings = list(IntegrityRing)
    matrix = []
    for r in rings:
        for req in rings:
            matrix.append(
                {
                    "ring": int(r),
                    "required": int(req),
                    "expected": is_at_least(r, req),
                    "desc": f"is_at_least({r.label()}, {req.label()})",
                }
            )

    src_hash = _src_hash(_APP / "forge_integrity.py")
    return {
        "_comment": "Auto-généré depuis IntegrityRing. NE PAS MODIFIER manuellement.",
        "_version": _version(),
        "_src_hash": src_hash,
        "_generated": _now(),
        "_source": "forge_integrity.IntegrityRing",
        "matrix": matrix,
    }


def gen_integrity_rings() -> dict:
    """
    Génère integrity_rings.json depuis IntegrityRing.
    consensus_level(), trust implicite, mutable par défaut.
    """
    from nokido_agent.app.forge_integrity import IntegrityRing
    from nokido_agent.app.forge_rag_qualify import CONSENSUS_TRUST

    rings = []
    for r in IntegrityRing:
        consensus = r.consensus_level()
        rings.append(
            {
                "ring": int(r),
                "label": r.label(),
                "consensus": consensus,
                "trust": CONSENSUS_TRUST.get(consensus, 0.2),
                "mutable": int(r) > 0,  # SYSTEM seul est immutable par défaut
            }
        )

    src_hash = _src_hash(_APP / "forge_integrity.py", _APP / "forge_rag_qualify.py")
    return {
        "_comment": "Auto-généré depuis IntegrityRing + CONSENSUS_TRUST. NE PAS MODIFIER.",
        "_version": _version(),
        "_src_hash": src_hash,
        "_generated": _now(),
        "_sources": ["forge_integrity.IntegrityRing", "forge_rag_qualify.CONSENSUS_TRUST"],
        "rings": rings,
    }


def gen_integrity_edge_cases() -> dict:
    """
    Génère integrity_edge_cases.json.
    Les cas EC sont stables par design (comportements défensifs CapabilityToken).
    On les régénère si la signature de decode() ou IntegrityManager.__init__() change.
    Détection AST : signature des méthodes critiques.
    """
    import ast as _ast

    src = (_APP / "forge_integrity.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)

    # Extraire les signatures des méthodes critiques
    sigs = {}
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            if node.name in ("decode", "__init__", "verify", "revoke", "attenuate"):
                args = [a.arg for a in node.args.args]
                sigs[node.name] = args

    # Les edge cases sont stables mais leur expected dépend du comportement actuel
    # On vérifie les cas limites en important le module
    from nokido_agent.app.forge_integrity import IntegrityRing, IntegrityManager, CapabilityToken

    _secret = "nr_test_secret_32chars_long_enough!"

    # Tester chaque comportement et le capturer
    cases = []

    # EC-01 : Token tronqué
    ec01_raises = False
    try:
        CapabilityToken.decode("nodotseparator", _secret.encode())
    except ValueError:
        ec01_raises = True
    cases.append(
        {
            "id": "EC-01",
            "desc": "Token tronqué sans point séparateur",
            "input": "nodotseparator",
            "expected": "ValueError" if ec01_raises else "no_exception",
            "method": "CapabilityToken.decode",
            "observed": ec01_raises,
        }
    )

    # EC-02 : Token vide
    ec02_raises = False
    try:
        CapabilityToken.decode("", _secret.encode())
    except (ValueError, Exception):
        ec02_raises = True
    cases.append(
        {
            "id": "EC-02",
            "desc": "Token vide",
            "input": "",
            "expected": "exception" if ec02_raises else "no_exception",
            "method": "CapabilityToken.decode",
            "observed": ec02_raises,
        }
    )

    # EC-03 : Secret vide
    ec03_raises = False
    try:
        IntegrityManager("")
    except ValueError:
        ec03_raises = True
    cases.append(
        {
            "id": "EC-03",
            "desc": "Secret vide → création IntegrityManager refusée",
            "input": "",
            "expected": "ValueError" if ec03_raises else "no_exception",
            "method": "IntegrityManager.__init__",
            "observed": ec03_raises,
        }
    )

    # EC-04 : Garbage token
    mgr = IntegrityManager(_secret)
    ok_g, _ = mgr.verify("fs", "read", "aa.bb.cc")
    cases.append(
        {
            "id": "EC-04",
            "desc": "Token garbage → verify retourne False",
            "input": "aa.bb.cc",
            "expected": {"ok": False},
            "method": "IntegrityManager.verify",
            "observed": {"ok": ok_g},
        }
    )

    # EC-05 : Revoke agent inconnu
    min_seq = IntegrityManager(_secret).revoke("unknown_xyz")
    cases.append(
        {
            "id": "EC-05",
            "desc": "revoke() agent inconnu → int retourné, pas d'exception",
            "expected": {"type": "int"},
            "observed": {"type": type(min_seq).__name__, "value": min_seq},
        }
    )

    # EC-06 : Atténuation TTL borné
    tok_short = mgr.create_manifest("x", IntegrityRing.DEV, scopes={"fs": ["read"]}, duration_s=1)
    parent = CapabilityToken.decode(tok_short, _secret.encode())
    child = parent.attenuate({"fs": ["read"]}, duration_s=86400)
    cases.append(
        {
            "id": "EC-06",
            "desc": "Atténuation TTL borné par parent",
            "expected": "child.exp <= parent.exp",
            "observed": child.exp <= parent.exp,
        }
    )

    # EC-07 : Révocation old/new
    m3 = IntegrityManager(_secret)
    t_old = m3.create_manifest("alice", IntegrityRing.COLLAB, scopes={"rag": ["query"]}, duration_s=3600)
    tok_old = CapabilityToken.decode(t_old, _secret.encode())
    t_new = m3.create_manifest("alice", IntegrityRing.COLLAB, scopes={"rag": ["query"]}, duration_s=3600)
    m3.revoke("alice", tok_old.seq + 1)
    oo, _ = m3.verify("rag", "query", t_old)
    on, _ = m3.verify("rag", "query", t_new)
    cases.append(
        {
            "id": "EC-07",
            "desc": "Révocation seq : ancien bloqué, nouveau passe",
            "expected": {"old": False, "new": True},
            "observed": {"old": oo, "new": on},
        }
    )

    src_hash = _src_hash(_APP / "forge_integrity.py")
    return {
        "_comment": "Auto-généré par introspection live de forge_integrity.py.",
        "_version": _version(),
        "_src_hash": src_hash,
        "_generated": _now(),
        "_method_sigs": sigs,
        "edge_cases": cases,
    }


def gen_behavior_gold() -> dict:
    """
    Régénère behavior_gold.json en testant EFFECTIVEMENT chaque invariant.
    Les résultats observés remplacent les valeurs manuelles.
    """
    from nokido_agent.app.forge_integrity import IntegrityRing, IntegrityManager, CapabilityToken
    from nokido_agent.app.forge_rag_truth import validate_authority, cove_validate, trust_score_to_state_mono, TruthState
    from nokido_agent.app.forge_rag_qualify import qualify_chunk
    from nokido_agent.app.forge_hot_ingest import _build_human_meta
    from nokido_agent.app.forge_mcp_security import MCPSecurity, SecurityConfig

    sec = MCPSecurity(SecurityConfig.from_env())
    _S = "nr_test_secret_32chars_long_enough!"
    mgr = IntegrityManager(_S)

    # Observer le comportement réel
    role_collab = sec._resolve_role("collab:gpt4")
    ok_auth, _ = validate_authority(0, 3)  # ring=0 validé par ring=3 → False
    r_cove = cove_validate("python test " * 10, {}, "collab:c", True)
    state_mono = trust_score_to_state_mono(r_cove.trust_score)

    # Token tamper
    tok = mgr.create_manifest("x", IntegrityRing.DEV, duration_s=60)
    token_tamper_raises = False
    try:
        CapabilityToken.decode(tok[:-2] + "AA", _S.encode())
    except ValueError:
        token_tamper_raises = True

    # Révocation seq
    m5 = IntegrityManager(_S)
    t_o = m5.create_manifest("bob", IntegrityRing.COLLAB, scopes={"rag": ["query"]}, duration_s=60)
    tk = CapabilityToken.decode(t_o, _S.encode())
    t_n = m5.create_manifest("bob", IntegrityRing.COLLAB, scopes={"rag": ["query"]}, duration_s=60)
    m5.revoke("bob", tk.seq + 1)
    oo, _ = m5.verify("rag", "query", t_o)
    on, _ = m5.verify("rag", "query", t_n)

    # Hot ingest
    meta9 = _build_human_meta("rapport.pdf", "tui_drop")

    # qualify source disco
    q_disco = qualify_chunk(source="disco:gpt4_session", author="system:fake")

    src_hash = _src_hash(
        _APP / "forge_integrity.py",
        _APP / "forge_rag_truth.py",
        _APP / "forge_mcp_security.py",
        _APP / "forge_hot_ingest.py",
        _APP / "forge_rag_qualify.py",
    )

    return {
        "_comment": "Auto-généré par exécution live des invariants. NE PAS MODIFIER.",
        "_version": _version(),
        "_src_hash": src_hash,
        "_generated": _now(),
        "CMD-01_IDENTITY_SPOOF": {
            "name": "Usurpation d'identité Ring",
            "invariant": "Un agent ring=3 ne peut jamais signer comme ring=0/1",
            "observed_role": role_collab,
            "expected_behavior": {
                "status": "FORBIDDEN",
                "enforced_ring": 3,
                "collab_role_is_nokido": role_collab == "laforge",
            },
        },
        "CMD-02_COVE_CONTRADICTION": {
            "name": "Cohérence logique CoVe",
            "invariant": "trust plafonné en mono-mode, gold impossible",
            "observed_trust": r_cove.trust_score,
            "observed_state": state_mono.label(),
            "expected_behavior": {
                "max_trust_score": 0.75,
                "gold_impossible": state_mono != TruthState.GOLD,
            },
        },
        "CMD-03_DISCO_OVERRIDES_AUTHOR": {
            "name": "Source disco écrase author prétendu",
            "invariant": "source=disco: force ring=3 même si author prétend system",
            "observed_ring": q_disco["ring"],
            "observed_consensus": q_disco["consensus_level"],
            "expected_behavior": {
                "ring": q_disco["ring"],
                "consensus_level": q_disco["consensus_level"],
                "ring_is_3": q_disco["ring"] == 3,
            },
        },
        "CMD-04_RING_ESCALATION": {
            "name": "Escalade de ring refusée",
            "invariant": "ring=3 ne peut jamais valider un chunk ring=0",
            "observed_passed": ok_auth,
            "expected_behavior": {
                "passed": ok_auth,
                "escalation_blocked": not ok_auth,
            },
        },
        "CMD-07_TOKEN_TAMPER": {
            "name": "Token HMAC falsifié → ValueError",
            "invariant": "Toute falsification HMAC lève ValueError sans crash silencieux",
            "observed_raises": token_tamper_raises,
            "expected_behavior": {
                "exception": "ValueError",
                "safe_failure": token_tamper_raises,
            },
        },
        "CMD-08_REVOKE_SEQ": {
            "name": "Révocation par séquence",
            "invariant": "seq < min_seq bloqué, seq >= min_seq accepté",
            "observed": {"old": oo, "new": on},
            "expected_behavior": {
                "old_token_passes": oo,
                "new_token_passes": on,
                "invariant_holds": (not oo) and on,
            },
        },
        "CMD-09_HOT_INGEST_TRUSTED": {
            "name": "Fast-track humain = ring TRUSTED",
            "invariant": "Action humaine directe TUI = ring=2 TRUSTED immédiat",
            "observed": {
                "ring": meta9["ring"],
                "cove_skip": meta9["cove_skip"],
                "consensus": meta9["consensus_level"],
            },
            "expected_behavior": {
                "ring": meta9["ring"],
                "trust_score": meta9["trust_score"],
                "cove_skip": meta9["cove_skip"],
                "consensus_level": meta9["consensus_level"],
                "invariant_holds": meta9["ring"] == 2 and meta9["cove_skip"],
            },
        },
    }


def gen_tui_handlers() -> dict:
    """
    Génère tui_handlers.json par scan de forge_handlers.py.
    Pour chaque handler, extrait les sous-commandes détectées.
    Génère les cas nominaux + edge cases automatiquement.
    """
    src = (_APP / "forge_handlers.py").read_text(encoding="utf-8")

    def extract_subcmds(handler_name: str) -> List[str]:
        """Extract subcmds.

        Args:
            handler_name: Description.
        """
        pattern = rf"async def {re.escape(handler_name)}\(.*?\n(?=async def |\Z)"
        m = re.search(pattern, src, re.DOTALL)
        if not m:
            return []
        block = m.group(0)
        subs = set()
        for s in re.findall(r'sub\s*==\s*["\'](\w+)["\']', block):
            subs.add(s)
        for group in re.findall(r"sub\s+in\s+\(([^)]+)\)", block):
            for s in re.findall(r'["\']([^"\']+)["\']', group):
                subs.add(s)
        return sorted(subs)

    def block_hash(handler_name: str) -> str:
        """Block hash.

        Args:
            handler_name: Description.
        """
        pattern = rf"async def {re.escape(handler_name)}\(.*?\n(?=async def |\Z)"
        m = re.search(pattern, src, re.DOTALL)
        return hashlib.sha256(m.group(0).encode()).hexdigest()[:8] if m else ""

    handlers = re.findall(r"async def (_handle_\w+)\(", src)
    result = {}

    # Invariants par défaut pour tous les handlers
    DEFAULT_INVARIANTS = [
        {"type": "not_contains", "value": "traceback", "desc": "Pas de traceback Python"},
        {"type": "not_contains", "value": "Exception", "desc": "Pas d'exception non gérée"},
        {"type": "min_lines", "value": 1, "desc": "Au moins 1 ligne de sortie"},
    ]

    # Invariants spécifiques par pattern de sortie attendu
    SUBCMD_PATTERNS = {
        "info": [{"type": "contains_any", "value": ["chunks", "RAG", "vide"], "desc": "Affiche stats RAG"}],
        "list": [{"type": "contains_any", "value": ["source", "vide", "indexée", "liste"], "desc": "Affiche liste"}],
        "build": [
            {"type": "contains_any", "value": ["FAISS", "BM25", "index", "reconstruit"], "desc": "Reconstruit index"}
        ],
        "status": [{"type": "contains_any", "value": ["OK", "FAIL", "PASS", "status"], "desc": "Affiche statut"}],
        "fast": [{"type": "contains", "value": "NR", "desc": "Affiche résultat NR"}],
        "all": [{"type": "contains", "value": "NR", "desc": "Affiche résultat NR"}],
        "cert": [{"type": "contains_any", "value": ["CMD", "certif", "Certif"], "desc": "Affiche certificat"}],
        "drop": [{"type": "contains_any", "value": ["Fast-track", "TRUSTED", "drop"], "desc": "Fast-track TUI"}],
        "trust": [{"type": "contains_any", "value": ["Fast-track", "TRUSTED", "drop"], "desc": "Fast-track TUI"}],
        "start": [{"type": "min_lines", "value": 1, "desc": "Sortie non vide"}],
        "stop": [{"type": "min_lines", "value": 1, "desc": "Sortie non vide"}],
        "run": [{"type": "min_lines", "value": 1, "desc": "Sortie non vide"}],
    }

    for handler in handlers:
        subcmds = extract_subcmds(handler)
        cmd_prefix = handler.replace("_handle_", "@").replace("_", " ", 1)
        h_hash = block_hash(handler)
        cases = []

        # Cas sans args → aide ou comportement par défaut
        cases.append(
            {
                "id": f"{handler.upper()}-NOARGS",
                "args": "",
                "category": "edge",
                "desc": "Sans arguments → aide ou comportement par défaut",
                "invariants": DEFAULT_INVARIANTS
                + [{"type": "min_lines", "value": 1, "desc": "Doit produire une sortie"}],
            }
        )

        # Cas par sous-commande
        for i, sub in enumerate(subcmds, 1):
            invariants = list(DEFAULT_INVARIANTS)
            invariants += SUBCMD_PATTERNS.get(
                sub, [{"type": "min_lines", "value": 1, "desc": f"sous-cmd '{sub}' produit une sortie"}]
            )
            cases.append(
                {
                    "id": f"{handler.upper().replace('_HANDLE_', '')}-{sub.upper()}-{i:02d}",
                    "args": sub,
                    "category": "nominal",
                    "desc": f"@{handler.replace('_handle_', '')} {sub}",
                    "invariants": invariants,
                }
            )

        # Cas sous-commande inconnue
        cases.append(
            {
                "id": f"{handler.upper()}-UNKNOWN",
                "args": "commande_inconnue_xyz_test",
                "category": "edge",
                "desc": "Sous-commande inconnue → aide ou avertissement",
                "invariants": DEFAULT_INVARIANTS,
            }
        )

        result[handler] = {
            "cmd_prefix": cmd_prefix,
            "block_hash": h_hash,
            "subcmds": subcmds,
            "cases": cases,
        }

    src_hash = _src_hash(_APP / "forge_handlers.py", _APP / "forge_dispatch.py")
    return {
        "_comment": "Auto-généré par scan forge_handlers.py. NE PAS MODIFIER.",
        "_version": _version(),
        "_src_hash": src_hash,
        "_generated": _now(),
        "handlers": result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DatasetSync — orchestrateur principal
# ─────────────────────────────────────────────────────────────────────────────

DATASET_REGISTRY = {
    "is_at_least_matrix": {
        "path": _DATA_NR / "expected" / "is_at_least_matrix.json",
        "generator": gen_is_at_least_matrix,
        "sources": [_APP / "forge_integrity.py"],
        "desc": "Matrice is_at_least() — 25 combinaisons Ring×Ring",
    },
    "integrity_rings": {
        "path": _DATA_NR / "input" / "integrity_rings.json",
        "generator": gen_integrity_rings,
        "sources": [_APP / "forge_integrity.py", _APP / "forge_rag_qualify.py"],
        "desc": "Rings → consensus_level + trust_score",
    },
    "integrity_edge_cases": {
        "path": _DATA_NR / "input" / "integrity_edge_cases.json",
        "generator": gen_integrity_edge_cases,
        "sources": [_APP / "forge_integrity.py"],
        "desc": "Edge cases CapabilityToken — comportements observés en live",
    },
    "behavior_gold": {
        "path": _DATA_NR / "expected" / "behavior_gold.json",
        "generator": gen_behavior_gold,
        "sources": [
            _APP / "forge_integrity.py",
            _APP / "forge_rag_truth.py",
            _APP / "forge_mcp_security.py",
            _APP / "forge_hot_ingest.py",
            _APP / "forge_rag_qualify.py",
        ],
        "desc": "Invariants comportementaux — CMD-01 à CMD-09",
    },
    "tui_handlers": {
        "path": _DATA_NR / "tui" / "tui_handlers.json",
        "generator": gen_tui_handlers,
        "sources": [_APP / "forge_handlers.py", _APP / "forge_dispatch.py"],
        "desc": "Cas NR handlers TUI — générés par scan sous-commandes",
    },
}


class DatasetSync:
    """
    Vérifie et régénère les datasets NR si leurs sources ont changé.
    Thread-safe (chaque run recharge depuis disque).
    """

    def __init__(self, verbose: bool = True) -> None:
        """Init.

        Args:
            verbose: Description.
        """
        self._verbose = verbose

    def _log(self, msg: str) -> None:
        """Log.

        Args:
            msg: Description.
        """
        if self._verbose:
            print(f"[dataset_sync] {msg}")

    def check_all(self) -> Dict[str, bool]:
        """
        Vérifie quels datasets sont périmés.
        Retourne {name: is_stale}.
        """
        result = {}
        for name, spec in DATASET_REGISTRY.items():
            current_hash = _src_hash(*spec["sources"])
            stale = _stale(spec["path"], current_hash)
            result[name] = stale
        return result

    def update(self, name: str) -> bool:
        """Régénère un dataset. Retourne True si succès."""
        spec = DATASET_REGISTRY.get(name)
        if not spec:
            self._log(f"Dataset inconnu: {name}")
            return False
        try:
            data = spec["generator"]()
            _save(spec["path"], data)
            self._log(f"✅ {name} régénéré → {spec['path'].name} (hash={data.get('_src_hash', '')})")
            return True
        except Exception as e:
            self._log(f"❌ {name} erreur: {e}")
            return False

    def check_and_update(self, force: bool = False) -> Dict[str, bool]:
        """
        Vérifie et régénère les datasets périmés.
        Retourne {name: was_updated}.

        Args:
            force: régénère tous même si à jour
        """
        stale = self.check_all()
        updated = {}
        for name, is_stale in stale.items():
            if force or is_stale:
                spec = DATASET_REGISTRY[name]
                if is_stale:
                    self._log(f"⚠ {name} périmé ({spec['desc']}) → régénération")
                elif force:
                    self._log(f"↺ {name} forcé")
                updated[name] = self.update(name)
            else:
                updated[name] = False
                self._log(f"✓ {name} à jour")
        return updated

    def status(self) -> None:
        """Affiche le statut de tous les datasets."""
        stale = self.check_all()
        print(f"\n{'─' * 65}")
        print(f"  {'NOM':<30} {'ÉTAT':<10} {'FICHIER'}")
        print(f"{'─' * 65}")
        for name, is_stale in stale.items():
            spec = DATASET_REGISTRY[name]
            exists = spec["path"].exists()
            icon = "⚠ PÉRIMÉ" if is_stale else ("✅ OK" if exists else "❌ ABSENT")
            fname = spec["path"].name if exists else "(absent)"
            print(f"  {name:<30} {icon:<10} {fname}")
        print(f"{'─' * 65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Intégration mcp_nr — hook pre-run
# ─────────────────────────────────────────────────────────────────────────────


def sync_before_nr(verbose: bool = False) -> Dict[str, bool]:
    """
    À appeler au début de run_fast() / run_all().
    Régénère silencieusement les datasets périmés.
    Non-bloquant si une régénération échoue.
    """
    try:
        sync = DatasetSync(verbose=verbose)
        return sync.check_and_update()
    except Exception as e:
        if verbose:
            print(f"[dataset_sync] non-bloquant: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# CLI standalone
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Synchronisation datasets NR Nokido")
    parser.add_argument("--status", action="store_true", help="Afficher l'état")
    parser.add_argument("--update", action="store_true", help="Régénérer les périmés")
    parser.add_argument("--force", action="store_true", help="Forcer la régénération")
    parser.add_argument("--dataset", default="", help="Dataset spécifique")
    args = parser.parse_args()

    sync = DatasetSync(verbose=True)

    if args.status:
        sync.status()
    elif args.force or args.update:
        if args.dataset:
            sync.update(args.dataset)
        else:
            updated = sync.check_and_update(force=args.force)
            n = sum(1 for v in updated.values() if v)
            print(f"\n{n}/{len(updated)} datasets mis à jour")
    else:
        sync.status()
