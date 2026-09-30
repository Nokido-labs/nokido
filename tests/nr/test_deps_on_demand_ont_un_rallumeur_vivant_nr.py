"""NR — une dep ON-DEMAND exige un RALLUMEUR non gele, sinon c'est un defer eternel.

CE QUE CE GARDE AURAIT VU EN 15 JOURS (mesure 2026-09-20) :

    NokidoEpistemicSoif   disabled=false   deps = [8099, 8100, 6333]
      :8099  OUVERT   <- NokidoLlamaEmbed est un service PERMANENT
      :6333  OUVERT
      :8100  REFUSED  <- NokidoLlamaReranker  disabled = true
                         ne s'allume QUE sur l'intention `rerank.wanted`
                         unique consommateur : forge_llama_keeper._piliers_on_demand
                         or NokidoLlamaKeeper  disabled = true depuis le 2026-09-05
                         (gele pour un defaut du CODER, etranger aux piliers RAG)

Le superviseur POSE pourtant l'intention a chaque tentative (`declareDepWanted`,
supervisor.ts:1019, remede cable le 2026-08-10 contre cette circularite exacte,
qui nomme meme le service dans son commentaire). L'emission REUSSIT. Personne ne
recoit. Le service reste en `defer` indefiniment, et rien ne crie -- c'est la
classe de defaut « emettre reussit toujours, meme sans personne en face ».

Dernier pouls du keeper : 2026-09-05T20:36:02. Heure de mort de la soif notee au
SSoT : 2026-09-05 20h36. La MEME MINUTE.

LE CONTRAT GARDE ICI, et rien d'autre : si un service actif declare en `deps` un
port servi par un service `disabled` (donc on-demand), alors le rallumeur de ce
port doit etre lui-meme non `disabled`. Sinon la dependance est structurellement
insatisfiable et le defer est eternel.

CE QUE CE NR NE GARDE PAS, dit explicitement : il ne juge pas si le rallumeur
TOURNE a l'instant t (ce serait une sonde sur la MACHINE, pas sur le code --
faute payee le 2026-09-19). Il juge la COHERENCE DECLARATIVE du SSoT, qui est
une propriete du depot et se verifie partout de la meme facon.
"""
from __future__ import annotations

import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parent.parent.parent
TOML = RACINE / "proxy_deno" / "core" / "services.toml"

# port -> drapeau d'intention, copie de DEP_INTENT (supervisor.ts:997).
# Duplique volontairement : un NR qui importerait la table qu'il verifie ne
# verifierait rien (« un instrument ne lit jamais son propre vocabulaire »).
DEP_INTENT = {8099: "embed.wanted", 8100: "rerank.wanted",
              8091: "llama.wanted", 8080: "llama.wanted", 1234: "lmstudio.wanted"}

# Qui rallume quoi. Source : forge_llama_keeper._PILIERS (L425) et la boucle
# on-demand du meme module.
RALLUMEUR = {8099: "NokidoLlamaKeeper", 8100: "NokidoLlamaKeeper",
             8091: "NokidoLlamaKeeper", 8080: "NokidoLlamaKeeper"}


def _services() -> dict:
    """Rend {nom: {'disabled': bool, 'deps': [int], 'port': int|None}}.

    Parse volontairement simple et BORNE : on lit les blocs `[[service]]` du
    SSoT. Si le fichier devient illisible, on le DIT par un skip explicite --
    jamais un dict vide, qui ferait passer ce NR au vert sur une absence.
    """
    try:
        brut = TOML.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        pytest.skip(f"services.toml ILLISIBLE ({exc.__class__.__name__}) "
                    "-- INDETERMINE, surtout pas 'aucun service'")
    out: dict[str, dict] = {}
    for bloc in brut.split("[[service]]")[1:]:
        m = re.search(r'^name\s*=\s*"([^"]+)"', bloc, re.M)
        if not m:
            continue
        nom = m.group(1)
        dis = re.search(r"^disabled\s*=\s*(true|false)", bloc, re.M)
        deps = re.search(r"^deps\s*=\s*\[([^\]]*)\]", bloc, re.M)
        port = re.search(r"^port\s*=\s*(\d+)", bloc, re.M)
        out[nom] = {
            "disabled": bool(dis and dis.group(1) == "true"),
            "deps": [int(x) for x in re.findall(r"\d+", deps.group(1))] if deps else [],
            "port": int(port.group(1)) if port else None,
        }
    if not out:
        pytest.skip("aucun bloc [[service]] reconnu -- parse a revoir, pas un vert")
    return out


def _proprietaire_du_port(services: dict, port: int) -> str | None:
    for nom, d in services.items():
        if d["port"] == port:
            return nom
    return None


def test_le_ssot_des_services_est_lisible_et_non_vide():
    """Garde d'abord l'instrument : un parse muet rendrait tous les autres verts."""
    s = _services()
    assert len(s) > 20, f"seulement {len(s)} services parses -- le parse ment"
    assert "NokidoEpistemicSoif" in s, "le service temoin de ce NR a disparu du SSoT"


def test_aucune_dep_on_demand_sans_rallumeur_actif():
    """LE COEUR DU CONTRAT.

    Un service ACTIF qui depend d'un port servi par un service `disabled` compte
    sur un rallumage par intention. Si le rallumeur est lui-meme `disabled`, la
    porte ne s'ouvrira jamais et le defer est eternel -- sans aucun cri.
    """
    services = _services()
    fautes = []
    for nom, d in services.items():
        if d["disabled"] or not d["deps"]:
            continue
        for port in d["deps"]:
            proprio = _proprietaire_du_port(services, port)
            if proprio is None or not services[proprio]["disabled"]:
                continue  # port permanent ou hors SSoT : pas le sujet de ce NR
            rall = RALLUMEUR.get(port)
            if rall is None:
                fautes.append(
                    f"{nom} depend de :{port} ({proprio}, disabled) et AUCUN "
                    f"rallumeur n'est connu pour ce port")
            elif services.get(rall, {}).get("disabled", True):
                fautes.append(
                    f"{nom} depend de :{port} ({proprio}, disabled=true, "
                    f"on-demand via {DEP_INTENT.get(port, '?')}) mais son "
                    f"rallumeur {rall} est disabled=true -> defer ETERNEL")
    assert not fautes, (
        "dependance(s) structurellement insatisfiable(s) :\n  - "
        + "\n  - ".join(fautes))


def test_un_port_on_demand_a_bien_un_drapeau_declare():
    """Un service `disabled` avec un port doit avoir une intention nommee.

    Sans drapeau, `declareDepWanted` rend sans rien ecrire (`if (!flag) return`)
    et personne ne saura jamais que le corps le veut.
    """
    services = _services()
    orphelins = [
        f"{nom} (:{d['port']})" for nom, d in services.items()
        if d["disabled"] and d["port"] and d["port"] in RALLUMEUR
        and d["port"] not in DEP_INTENT]
    assert not orphelins, (
        "service(s) on-demand sans drapeau d'intention declare : "
        + ", ".join(orphelins))
