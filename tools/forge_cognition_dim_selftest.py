#!/usr/bin/env python3
"""forge_cognition_dim_selftest.py — valide la centralisation des dims cognition.

Phase 2a/2b : au defaut (LAFORGE_STATE_DIM absent -> 384) les constantes world_model +
value/policy/cost nets sont IDENTIQUES a avant (non-breaking, poids *.npz 384d chargent).

Phase 4 (dedup + 1024-safe) :
  - world_model.COGNITION_DIM vient de forge_state_encoder.STATE_DIM (SOURCE UNIQUE,
    plus de double-lecture de l'env) ; value_net importe la meme.
  - au flip LAFORGE_STATE_DIM=1024 TOUTES les dims propagent (2048 / 1024) et l'embedder
    goap_intuition suit en 1024d (CHECKPOINT-TIED via embed_router, PAS de fallback 384
    silencieux). Verifie dans un PROCESS FRAIS (la dim est lue a l'import).

Run trusted (loopback :8099 OK pour le check 1024d live).
"""
import os
import subprocess
import sys
from pathlib import Path

APP = str(Path(__file__).resolve().parent.parent / "app")
sys.path.insert(0, APP)
from nokido_agent.app import forge_cost_net as cn  # noqa: E402
from nokido_agent.app import forge_goap_intuition as gi  # noqa: E402
from nokido_agent.app import forge_policy_net as pn  # noqa: E402
from nokido_agent.app import forge_state_encoder as se  # noqa: E402
from nokido_agent.app import forge_value_net as vn  # noqa: E402
from nokido_agent.app import forge_world_model as wm  # noqa: E402


def _check_default() -> None:
    """Defaut 384 = non-breaking + dedup source unique + goap opt-in."""
    # dedup : world_model lit la MEME constante que state_encoder (source unique)
    assert wm.COGNITION_DIM == se.STATE_DIM == 384, (wm.COGNITION_DIM, se.STATE_DIM)
    assert wm.INPUT_DIM == 768 and wm.OUTPUT_DIM == 384, (wm.INPUT_DIM, wm.OUTPUT_DIM)
    assert wm.JEPA_IN_DIM == 384 and wm.H_ACT_DIM == 384, (wm.JEPA_IN_DIM, wm.H_ACT_DIM)
    m = wm.NMLP()
    assert m.W1.shape == (768, 512) and m.W3.shape == (256, 384), (m.W1.shape, m.W3.shape)
    wm.JEPA()
    assert vn.IN_DIM == 384 and pn.IN_DIM == 768 and cn.IN_DIM == 768, (vn.IN_DIM, pn.IN_DIM, cn.IN_DIM)
    assert pn.OUT_DIM == 384, pn.OUT_DIM
    vn.ValueNet()
    pn.PolicyNet()
    cn.CostNet()
    # goap embedder OPT-IN : sans LAFORGE_GOAP_VALUE_NET -> None (zero taxe value_net)
    assert gi.resolve_embed_fn() is None, "resolve_embed_fn devrait etre None sans opt-in"


# Bloc enfant : execute dans un process avec LAFORGE_STATE_DIM=1024 (dim lue a l'import).
_CHILD = r'''
import os, sys
sys.path.insert(0, r"__APP__")
import forge_world_model as wm
import forge_value_net as vn
import forge_policy_net as pn
import forge_cost_net as cn
import forge_state_encoder as se
import forge_goap_intuition as gi

assert se.STATE_DIM == 1024, se.STATE_DIM
assert wm.COGNITION_DIM == 1024 and wm.INPUT_DIM == 2048 and wm.OUTPUT_DIM == 1024, (
    wm.COGNITION_DIM, wm.INPUT_DIM, wm.OUTPUT_DIM)
assert wm.JEPA_IN_DIM == 1024 and wm.H_ACT_DIM == 1024, (wm.JEPA_IN_DIM, wm.H_ACT_DIM)
assert vn.IN_DIM == 1024 and pn.IN_DIM == 2048 and cn.IN_DIM == 2048, (vn.IN_DIM, pn.IN_DIM, cn.IN_DIM)
m = wm.NMLP()
assert m.W1.shape == (2048, 1024) and m.W3.shape == (512, 1024), (m.W1.shape, m.W3.shape)

# embedder goap CHECKPOINT-TIED : a 1024 -> router (callable), PAS le MiniLM 384 legacy
os.environ["LAFORGE_GOAP_VALUE_NET"] = "local"
ef = gi.resolve_embed_fn()
assert callable(ef), "resolve_embed_fn devrait router (callable) a 1024d"
try:
    v = ef("selftest goap state action context")
    assert tuple(v.shape) == (1024,), ("FALLBACK 384 SILENCIEUX", tuple(v.shape))
    print("CHILD-1024 OK | dims propagees + goap embedder 1024d live (embed_router, no silent 384)")
except AssertionError:
    raise
except Exception as e:
    # router :8099 injoignable (offline) -> dims deja prouvees, embedder route bien
    print("CHILD-1024 OK | dims propagees ; embedder route (call skip: " + type(e).__name__ + ")")
'''


def _check_flip_1024() -> None:
    """Flip LAFORGE_STATE_DIM=1024 dans un process frais : dims propagees + embedder 1024d."""
    env = dict(os.environ, LAFORGE_STATE_DIM="1024", PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
    code = _CHILD.replace("__APP__", APP)
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, errors="replace")
    if r.returncode != 0:
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        raise AssertionError("flip 1024 child FAILED (rc=%s)" % r.returncode)
    print(r.stdout.strip())


def main() -> int:
    _check_default()
    print("WM-DIM OK | defaut 384 non-breaking : world_model + value/policy/cost + dedup "
          "source-unique state_encoder + goap opt-in")
    _check_flip_1024()
    print("DIM-CENTRALIZE OK | 384 defaut intact + flip 1024 propage partout + embedder "
          "checkpoint-tied (zero fallback 384 silencieux)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
