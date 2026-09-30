"""NR — aucun garde ne doit avoir de porte que le contraint puisse ouvrir.

Directive owner du 2026-09-13 : « plus de passe-droit sur la politique mise en
place ». Trois zones grises avaient ete reconnues par l'agent (Monitor hors
gouvernance, ecritures natives, lectures hors voie canonique) ; une QUATRIEME a
ete trouvee en lisant le garde lui-meme, et c'est la plus grave.

**LAYER 0 de `bash_guard`** saute toute la couche de routing quand un fichier
d'armement existe et date de moins de 30 min. Ce fichier vivait dans `sandbox/`
-- dossier mesure `(OI)(CI)(M)` pour `LaForgeSandboxUsers` le 2026-09-13. Le
compte contraint par le garde pouvait donc **desarmer le garde lui-meme**.
Exactement la forme de l'attestation DEV dont le dossier de jeton etait
inscriptible par le client : un garde n'est un garde que si son interrupteur
est hors de portee de ce qu'il contraint.

Aucune exploitation n'est jouee ici : l'ACL suffit a etablir la portee, et
fabriquer le motif d'attaque serait le geste qu'on cherche a rendre impossible.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

GUARD = ROOT / "tools" / "bash_guard.py"


def _source_guard() -> str:
    return GUARD.read_text(encoding="utf-8", errors="replace")


def test_l_interrupteur_du_garde_n_est_pas_dans_une_zone_inscriptible():
    """LE point : `sandbox/` est (M) pour le compte que le garde contraint."""
    src = _source_guard()
    # Ne lire QUE le code : la docstring cite `sandbox/` pour expliquer le
    # defaut. Un instrument ne lit jamais son propre vocabulaire.
    code = "\n".join(
        l for l in src.splitlines()
        if not l.lstrip().startswith("#") and '"""' not in l
    )
    m = re.search(r"_ARM_FILE\s*=\s*_ROOT\s*/\s*\"([^\"]+)\"", code)
    assert m, "impossible de localiser _ARM_FILE dans le code du garde"
    zone = m.group(1)
    assert zone != "sandbox", (
        "l'interrupteur du garde vit dans `sandbox/`, qui est (M) pour "
        "LaForgeSandboxUsers : le compte contraint peut desarmer son propre garde"
    )
    assert zone == "etat_protege", (
        f"interrupteur du garde dans une zone non durcie : {zone!r}"
    )


def test_le_bypass_reste_borne_dans_le_temps():
    """Un bypass sans TTL devient un etat, pas une derogation."""
    src = _source_guard()
    m = re.search(r"_DEV_TTL_S\s*=\s*(\d+)", src)
    assert m, "le bypass n'a plus de TTL"
    assert 0 < int(m.group(1)) <= 3600, "TTL du bypass hors borne raisonnable"


def test_la_couche_secrets_n_est_jamais_sautee():
    """LAYER 1 doit rester inconditionnelle, meme bypass arme."""
    src = _source_guard()
    assert "_dev_armed" in src
    # La denylist secrets s'execute AVANT tout test de bypass sur le routing.
    i_secret = src.find("SECRET_PATTERNS")
    i_layer2 = src.find("segment_ok")
    assert i_secret != -1 and i_layer2 != -1
    assert i_secret < i_layer2, (
        "la denylist secrets doit precedee le routing : un bypass de routing ne "
        "doit jamais pouvoir emporter la protection des secrets"
    )


def test_monitor_est_gouverne():
    """Monitor execute du shell natif : sans cablage, c'est un passe-droit."""
    settings = ROOT.parent / ".claude" / "settings.local.json"
    if not settings.exists():
        pytest.skip("settings hors perimetre lisible depuis ce compte")
    txt = settings.read_text(encoding="utf-8", errors="replace")
    matchers = re.findall(r'"matcher"\s*:\s*"([^"]*)"', txt)
    couvre = any(re.search(r"\bMonitor\b", m or "") for m in matchers)
    assert couvre, (
        "aucun hook ne matche `Monitor` : il execute du bash natif hors "
        "bash_guard, donc hors de la politique d'execution"
    )


def _decide(tool: str, tool_input: dict) -> str:
    """Decision du gate, lue dans le JSON -- pas dans le code de sortie.

    Piege paye le 2026-09-13 : `forge_tool_gate` rend TOUJOURS rc=0 et exprime
    son refus dans `hookSpecificOutput.permissionDecision`. Lire le rc faisait
    conclure « tout est autorise » sur un gate qui refusait correctement.
    """
    import forge_tool_gate as gate

    d = gate.decide("claude", "CLAUDE", tool, tool_input)
    return "deny" if d.get("action") == "block" else "allow"


def test_la_politique_n_est_pas_editable_par_l_agent():
    """Un agent qui peut reecrire ses hooks n'est pas garde."""
    for cible in (
        r"%USERPROFILE%/.claude/settings.json",
        r"%NOKIDO_WORKSPACE%/.claude/settings.local.json",
        r"%USERPROFILE%/.claude/hooks/x.py",
    ):
        assert _decide("Write", {"file_path": cible, "content": "x"}) == "deny", (
            f"ecriture native autorisee sur la politique : {cible}"
        )


def test_les_ecritures_legitimes_restent_possibles():
    """CONTROLE POSITIF : un garde qui refuse tout ne prouve rien."""
    ok = (
        r"%USERPROFILE%/.claude/projects/C--Users-user-Script-python-IA/memory/x.md",
        r"D:/Temp/claude/x/scratchpad/n.txt",
    )
    for cible in ok:
        assert _decide("Write", {"file_path": cible, "content": "x"}) == "allow", (
            f"ecriture legitime refusee : {cible} — le garde est trop large"
        )


def test_la_lecture_brute_du_depot_est_signalee():
    """Lire le depot en brut depuis action=python echappe aux bornes de lecture."""
    import hook_capability_gate as cap

    motifs = [p for p, _m in cap.REGLES if "read_text" in p]
    assert motifs, "aucune regle ne couvre la lecture brute du depot"
    rx = re.compile(motifs[0], re.IGNORECASE)
    assert rx.search('p = pathlib.Path(r"C:/x/Nokido/tools/a.py")\nt = p.read_text()')
    # Et il ne doit pas crier sur une lecture hors depot.
    assert not rx.search('p = Path("D:/Temp/scratch.txt")\nt = p.read_text()')


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
