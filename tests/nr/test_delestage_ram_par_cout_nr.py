"""NR -- la rafale RAM du superviseur deleste PAR COUT et ne fauche plus la regulation.

MESURE 2026-10-01 (journal du superviseur) : « 15:54:52 RAM 90.5% > 88% -- sleeping
non-essential services » puis 43 « Sleeping » d'un coup : noeud sinusal, sentinelle
anti-embolie, boite noire, coagulation, soif, executeurs. La pression venait d'ailleurs
(navigateur, fuite de handles mtkbtsvc ; RSS de l'embedder stable) : vingt organes de
20-60 Mo ne la soulageaient pas. Puis 27 services encore endormis a 81,5 % -- le reveil
n'avait lieu que sous 72 %, seuil que ce poste (base 65-80 %) n'atteint presque jamais.

Contrat garde ici (Hermetique : lit la source .ts, ne lance pas deno) :
- delestage : plus gros RSS d'abord, borne par cycle, arret a la cible, et hors seuil
  critique un gain non PROUVE (RSS illisible) ou derisoire n'endort RIEN -- et c'est dit ;
- reveil : moins couteux d'abord, seulement si la RAM estimee reste sous la cible ;
- seuils ordonnes : reveil < cible < sommeil < critique ;
- RSS lu dans le MEME tasklist que la vitalite (aucune sonde de plus dans la boucle) ;
- les quatre REGULATEURS sont exemptes de la rafale (classe de la decision owner du
  2026-09-25 pour le keeper), la soif reste une consommatrice soumise a la regulation.
Le lecteur RETIRE les commentaires : le commentaire du superviseur cite lui-meme les noms
de constantes, il ferait un faux vert (« un instrument ne lit jamais son propre vocabulaire »).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(30)

RACINE = Path(__file__).resolve().parents[2]
CORE = RACINE / "proxy_deno" / "core"
REGULATEURS = ("NokidoCardiacNode", "NokidoOrganPulse", "NokidoHubBlackbox", "NokidoCoagulation")


def _sans_commentaires(src: str) -> str:
    # `//` precede d'un blanc ou en debut de ligne : epargne « http:// » dans les chaines.
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", src)


def _corps(src: str, entete: str) -> str:
    i = src.index(entete)
    j = src.find("\n}\n", i)
    return src[i: j if j != -1 else len(src)]


def _constantes(src: str) -> dict:
    return {m.group(1): float(m.group(2)) for m in
            re.finditer(r"(?m)^const (RAM_\w+_PCT)\s*=\s*([0-9.]+)\s*;", src)}


def _verdict(src: str) -> list[str]:
    """Violations du contrat de delestage dans une source supervisor.ts (vide = conforme)."""
    src = _sans_commentaires(src)
    v = []
    try:
        boucle = _corps(src, "async function resourceLoop()")
    except ValueError:
        return ["resourceLoop introuvable : le lecteur ne voit plus la boucle"]
    i = boucle.find("sleeping non-essential services")
    j = boucle.find("Sleeping ${", i)
    if i == -1 or j == -1:
        return ["branche de delestage introuvable"]
    tri = boucle[i:j]
    if not re.search(r"\.sort\(\(a, b\) => \(b\.ko \?\? -1\) - \(a\.ko \?\? -1\)\)", tri):
        v.append("delestage sans tri par RSS decroissant : on endort dans l'ordre de declaration")
    if "DELESTAGE_MAX_PAR_CYCLE" not in tri or "RAM_CIBLE_PCT" not in tri:
        v.append("delestage sans borne par cycle ni cible : retour a la rafale qui fauche tout")
    if not re.search(r"!critique && \(ko === null \|\| ko < DELESTAGE_GAIN_MIN_KO\)\)\s*\{[^}]*continue;", tri):
        v.append("un gain non prouve ou derisoire est endormi hors seuil critique")
    if "rien endormi" not in boucle:
        v.append("un delestage qui n'endort rien se tait : pression hors portee non dite")
    k = boucle.find("} else if (memPct < RAM_WAKE_PCT)")
    w = boucle.find("Waking ${", k)
    if k == -1 or w == -1:
        v.append("branche de reveil introuvable")
    else:
        reveil = boucle[k:w]
        if not re.search(r"\(_rssKoAuSommeil\.get\(a\.def\.name\) \?\? RSS_INCONNU_KO\) -\s*"
                         r"\(_rssKoAuSommeil\.get\(b\.def\.name\) \?\? RSS_INCONNU_KO\)", reveil):
            v.append("reveil sans tri par cout croissant")
        if "> RAM_CIBLE_PCT" not in reveil or "if (tropCher) break;" not in reveil:
            v.append("reveil sans estimation de cout contre la cible : retour du flap du 2026-06-01")
    vit = _corps(src, "async function livingPids()")
    if "rss.set(p, ko)" not in vit or "_rssKoParPid = rss" not in vit:
        v.append("RSS non lu dans le tasklist de vitalite")
    if boucle.count("new Deno.Command") > 0:
        v.append("sonde de processus ajoutee DANS la boucle de ressources")
    c = _constantes(src)
    cles = ("RAM_WAKE_PCT", "RAM_CIBLE_PCT", "RAM_SLEEP_PCT", "RAM_CRITIQUE_PCT")
    if not all(n in c for n in cles):
        v.append("seuils illisibles : %s" % sorted(set(cles) - set(c)))
    elif not (c["RAM_WAKE_PCT"] < c["RAM_CIBLE_PCT"] < c["RAM_SLEEP_PCT"] < c["RAM_CRITIQUE_PCT"]):
        v.append("seuils desordonnes : %s" % {n: c[n] for n in cles})
    return v


def test_le_superviseur_reel_deleste_par_cout():
    v = _verdict((CORE / "supervisor.ts").read_text(encoding="utf-8"))
    assert v == [], "\n".join(v)


def test_le_reveil_n_attend_plus_un_seuil_jamais_atteint():
    """Base mesuree du poste : 65-80 %. Un reveil sous 72 % laissait 27 organes endormis a 81,5 %."""
    c = _constantes(_sans_commentaires((CORE / "supervisor.ts").read_text(encoding="utf-8")))
    assert c.get("RAM_WAKE_PCT", 0) >= 80, c


def test_le_lecteur_rougit_sur_l_ancienne_rafale():
    """L'ancienne forme (boucle sur tous les etats, kill sans ordre) DOIT etre refusee."""
    ancien = (
        'import { memUsagePct } from "./platform.ts";\n'
        "const RAM_SLEEP_PCT = 88;\nconst RAM_WAKE_PCT = 72;\n"
        "async function livingPids() {\n  return alive.size > 10 ? alive : null;\n}\n"
        "async function resourceLoop() {\n"
        "    if (memPct > RAM_SLEEP_PCT) {\n"
        "      log(`RAM ${memPct}% — sleeping non-essential services`);\n"
        "      for (const [, state] of states) {\n"
        "        if (!state.def.essential && !state.def.neverSleep) {\n"
        "          log(`Sleeping ${state.def.name}`);\n"
        "          state.proc.kill(\"SIGTERM\");\n        }\n      }\n"
        "    } else if (memPct < RAM_WAKE_PCT) {\n"
        "      if (state.status === \"sleeping\") { log(`Waking ${state.def.name}`); }\n"
        "    }\n}\n"
    )
    v = _verdict(ancien)
    assert any("tri par RSS" in x for x in v) and any("borne par cycle" in x for x in v), v
    assert any("seuils" in x for x in v), v


def test_le_lecteur_ignore_les_commentaires():
    """Une forme correcte citee SEULEMENT en commentaire ne vaut pas conformite."""
    src = "// const RAM_WAKE_PCT = 82;\n// rien endormi\nconst RAM_WAKE_PCT = 72;\n"
    assert "rien endormi" not in _sans_commentaires(src)
    assert _constantes(_sans_commentaires(src)) == {"RAM_WAKE_PCT": 72.0}
    assert "http://127.0.0.1:8766" in _sans_commentaires('fetch("http://127.0.0.1:8766/x")')


def test_les_regulateurs_sont_exemptes_et_la_soif_reste_consommatrice():
    services = tomllib.loads((CORE / "services.toml").read_text(encoding="utf-8"))["service"]
    par_nom = {s["name"]: s for s in services}
    for nom in REGULATEURS:
        s = par_nom[nom]
        assert s.get("neverSleep") is True, "%s endormi par la rafale RAM : la regulation s'eteint" % nom
        assert s.get("essential") is False, "%s : neverSleep suffit, essential changerait le boot" % nom
    assert not par_nom["NokidoEpistemicSoif"].get("neverSleep"), \
        "la soif est une CONSOMMATRICE (decision owner 2026-09-25) : elle reste soumise a la regulation"


def test_la_ram_totale_est_lue_sans_sous_processus():
    plat = _sans_commentaires((CORE / "platform.ts").read_text(encoding="utf-8"))
    corps = _corps(plat, "export function totalRamKo()")
    assert "systemMemoryInfo" in corps and "return null" in corps
    assert "Deno.Command" not in corps, "la boucle de ressources n'attend que des fonctions BORNEES"
