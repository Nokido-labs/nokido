"""forge_fleet_router.py — routeur de flotte Nokido (role-clustering + Context Anchoring).

Sélectionne un `llama-server` distant par LENTILLE (goap/security/...) parmi une flotte
déclarée dans `config/fleet.toml`, health-gated (ping /health avant de router, écarte les
morts). PAS de tensor/pipeline parallelism : on route des prompts (KB) en HTTP ; chaque
nœud infère à la vitesse de SA RAM locale. Ajouter une machine = +1 worker parallèle.

## Context Anchoring (le levier de perf une fois les tenseurs gardés locaux)
Le goulot restant = le PREFILL du contexte stable (system + repo_map, ~8KB) à CHAQUE appel.
llama.cpp réutilise le KV-cache du **plus long préfixe commun** d'une requête à l'autre,
sur un même slot, quand `cache_prompt: true`. Donc :
  - on met le contenu STABLE (system + repo_map) en TÊTE, IDENTIQUE entre appels ;
  - on met le DELTA variable (la fonction ciblée) en QUEUE ;
  - on épingle au même `id_slot` (slot KV-cache persistant) ;
→ le prefill recalculé ≈ taille du DELTA seulement (prefix-cache hit). Le préfixe ne doit
PAS changer (sinon invalidation → re-prefill) : anchre le vraiment stable, garde le volatil
en queue. `--slot-save-path` côté llama-server persiste les slots sur disque.

Couche placement-worker de `forge_durable_workflow` (workflow=orchestrateur, fleet_router=
placement, llama-server distant=activity). Découverte STATIQUE (zero-trust, cf wiki 20).

Stdlib only (tomllib + urllib). Démo : `python tools/forge_fleet_router.py --demo`.
"""
from __future__ import annotations

import argparse
import json
import time
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_FLEET = ROOT / "config" / "fleet.toml"


@dataclass
class Node:
    name: str
    url: str
    lenses: list[str]
    model: str = "default"
    anchor: bool = False
    anchor_id_slot: int | None = None


@dataclass
class FleetRouter:
    fleet_path: Path = _DEFAULT_FLEET
    nodes: list[Node] = field(default_factory=list)
    token: str | None = None
    health_path: str = "/health"
    health_timeout: float = 2.0
    health_ttl: float = 10.0

    def __post_init__(self):
        cfg = tomllib.loads(Path(self.fleet_path).read_text(encoding="utf-8"))
        f = cfg.get("fleet", {})
        self.health_path = f.get("health_path", self.health_path)
        self.health_timeout = float(f.get("health_timeout_s", self.health_timeout))
        self.health_ttl = float(f.get("health_ttl_s", self.health_ttl))
        self.token = self._resolve_token(f.get("token_secret"))
        for n in cfg.get("node", []):
            self.nodes.append(Node(
                name=n["name"], url=n["url"].rstrip("/"), lenses=list(n.get("lenses", [])),
                model=n.get("model", "default"), anchor=bool(n.get("anchor", False)),
                anchor_id_slot=n.get("anchor_id_slot")))
        self._health_cache: dict[str, tuple[float, bool]] = {}
        self._rr: dict[str, int] = {}

    @staticmethod
    def _resolve_token(key: str | None) -> str | None:
        if not key:
            return None
        try:
            import sys
            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_machine_vault import vault_get  # type: ignore
            return vault_get(key) or None
        except Exception:  # noqa: BLE001
            return None

    def health(self, node: Node) -> bool:
        now = time.monotonic()
        cached = self._health_cache.get(node.name)
        if cached and now - cached[0] < self.health_ttl:
            return cached[1]
        ok = False
        try:
            req = urllib.request.Request(node.url + self.health_path)
            with urllib.request.urlopen(req, timeout=self.health_timeout) as r:
                ok = 200 <= getattr(r, "status", 200) < 300
        except Exception:  # noqa: BLE001
            ok = False
        self._health_cache[node.name] = (now, ok)
        return ok

    def get_slot(self, lens: str = "default") -> Node | None:
        """Nœud SAIN dont les lentilles couvrent `lens` (round-robin). None si aucun vivant."""
        cand = [n for n in self.nodes if lens in n.lenses or "default" in n.lenses]
        pool = [n for n in cand if self.health(n)]
        if not pool:
            return None
        i = self._rr.get(lens, 0) % len(pool)
        self._rr[lens] = i + 1
        return pool[i]

    def anchored_payload(self, node: Node, *, system: str, repo_map: str = "",
                         messages: list[dict], cache_prompt: bool = True, **extra) -> dict:
        """Construit le payload chat avec PRÉFIXE STABLE ancré (system+repo_map) en tête et
        delta (`messages`) en queue. Contrat : garder system+repo_map IDENTIQUES entre appels
        pour le prefix-cache hit ; seul `messages` varie."""
        stable = system if not repo_map else f"{system}\n\n# REPO MAP (ancré — ne pas modifier)\n{repo_map}"
        payload = {"model": node.model,
                   "messages": [{"role": "system", "content": stable}, *messages], **extra}
        if node.anchor and cache_prompt:
            payload["cache_prompt"] = True                  # llama.cpp : réutilise KV-cache du préfixe
            if node.anchor_id_slot is not None:
                payload["id_slot"] = node.anchor_id_slot    # épingle au slot persistant
        return payload

    def call(self, node: Node, payload: dict, *, timeout: float = 120.0) -> dict:
        """POST {node.url}/v1/chat/completions (bearer si token). Synchrone (urllib)."""
        data = json.dumps(payload).encode()
        req = urllib.request.Request(node.url + "/v1/chat/completions", data=data,
                                     headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())


def _demo(path: str | Path = _DEFAULT_FLEET) -> int:
    fr = FleetRouter(Path(path))
    print(f"[fleet] {len(fr.nodes)} nœud(s), token={'oui' if fr.token else 'non'}")
    for n in fr.nodes:
        print(f"  {n.name:<16} {n.url:<28} health={fr.health(n)}  lenses={n.lenses}  anchor={n.anchor}")
    slot = fr.get_slot("goap")
    print(f"[fleet] get_slot('goap') -> {slot.name if slot else 'AUCUN nœud sain'}")
    if slot:
        p = fr.anchored_payload(slot, system="Tu es le planificateur GOAP de Nokido.",
                                repo_map="forge_goap_hub_bridge.py: plan()/execute_plan()",
                                messages=[{"role": "user", "content": "plan: corriger bug X"}])
        print(f"[anchor] cache_prompt={p.get('cache_prompt')} id_slot={p.get('id_slot')} "
              f"prefix_stable_len={len(p['messages'][0]['content'])} delta_msgs={len(p['messages']) - 1}")
        print("[anchor] préfixe stable (réutilisé entre appels) =", repr(p["messages"][0]["content"][:60]) + "...")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--fleet", default=str(_DEFAULT_FLEET))
    args = ap.parse_args()
    if args.demo:
        return _demo(args.fleet)
    print("usage: --demo ; sinon importer FleetRouter (get_slot/anchored_payload/call)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
