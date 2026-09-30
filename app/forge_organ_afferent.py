"""forge_organ_afferent.py — le nerf par lequel un organe EMET son etat.

Correction owner du 2026-08-25 : « le signal de vie devrait EMANER de l'organe ».
L'audit d'intention jugeait la vie par PALPATION — cpu, sockets, lus du dehors avec
psutil. Un observateur qui prend le pouls n'apprend jamais que « ca consomme » ; un
organe qui temoigne dit CE QU'IL FAIT. Mesure du jour : 18 services vivants sur 46 ne
tenaient leur contrat que par palpation, et parmi eux les plus critiques du corps —
le hub lui-meme, les deux etages de Qdrant, Ollama, le pont netcfg.

TROIS REGISTRES, et les confondre est le defaut qu'on corrige ici :
  AFFERENT_DIRECT  l'organe ECRIT lui-meme dans la moelle. C'est le pouls : il part
                   de l'organe, personne ne le lui demande.
  AFFERENT_MEDIE   l'organe REPOND sur lui-meme, dans SES termes, quand on
                   l'interroge (`/stats` rend `points_count`, pas un pourcentage de
                   CPU). C'est la prise de sang : le contenu vient de l'organe, la
                   demarche vient de nous. Un binaire tiers ne peut pas faire mieux,
                   et c'est deja incomparablement plus qu'une palpation.
  PALPATION        mesure prise SUR l'organe sans sa participation. Dernier recours.

Ce module ne palpe rien. Il fournit (1) `emettre` pour qu'un organe du corps batte
de lui-meme, (2) `battre_medies` pour recueillir le temoignage des organes tiers,
(3) `dernier_pouls` qui rend TROIS etats — un age, `None` si l'organe n'a JAMAIS
battu, et une raison quand la moelle est illisible. Jamais un booleen.

Usage :
    LAFORGE_PYTHON app/forge_organ_afferent.py --battre     # un tour de recueil
    LAFORGE_PYTHON app/forge_organ_afferent.py --etat       # qui bat, qui se tait
"""
from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/heartbeat afferent, interoception (sympathique)"

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_trace_spine as spine  # noqa: E402

# ---------------------------------------------------------------------------
# LES ORGANES QUI DOIVENT TEMOIGNER, et ce qu'ils disent d'EUX-MEMES.
# Chaque entree nomme l'interface par laquelle l'organe repond et les champs qui
# sont SA mesure — jamais une grandeur que nous lui appliquons du dehors.
# ---------------------------------------------------------------------------
MEDIES = {
    "NokidoMCP": {
        "organe": "SNC/hub",
        "url": "http://127.0.0.1:8766/health",
        "champs": ("status", "uptime_s", "tools", "version"),
        "note": "MEDIE faute de mieux : le hub est notre code, il DEVRAIT battre de "
                "lui-meme. Tant qu'il ne le fait pas, son /health reste son propre "
                "temoignage — mais l'innervation directe est la vraie cible.",
    },
    "NokidoQdrantServer": {
        "organe": "memoire/vecteurs",
        "url": "http://127.0.0.1:6333/collections/nokido_sovereign_rag",
        "champs": ("points_count", "segments_count", "status"),
        "note": "binaire tiers : ne peut pas ecrire dans notre moelle, mais rend SES "
                "propres compteurs.",
    },
    "NokidoQdrantSidecar": {
        "organe": "memoire/vecteurs",
        "url": "http://127.0.0.1:8098/stats",
        "champs": ("points_count", "vectors_count"),
        "note": "sert la recherche dense du hub depuis le 2026-08-25.",
    },
    "NokidoOllama": {
        "organe": "cognition/cerveaux",
        "url": "http://127.0.0.1:11434/api/tags",
        "champs": ("models",),
        "note": "ATTENTION, piege consigne : /api/tags rend un CACHE et peut mentir "
                "sur ce qui est reellement charge. Le temoignage est donc DATE mais "
                "sa fraicheur n'est pas garantie — a ne pas lire comme une preuve de "
                "capacite, seulement comme un signe de vie.",
    },
    "NokidoNetcfgMCP": {
        "organe": "SNC/peripherique",
        # :8768 = le MCP REEL. :8767 est le lazy PROXY, qui relaie ce meme /health —
        # d'ou deux reponses identiques et une confusion facile. Chaque organe est
        # interroge la ou IL vit, sinon on fait temoigner l'un a la place de l'autre.
        "url": "http://127.0.0.1:8768/health",
        "champs": ("ok", "server", "version", "auth_required"),
        "accepte_401": True,
        "note": "DEUX faux negatifs de MOI avant d'y arriver, le 2026-08-25 : j'ai "
                "sonde :7500/health (404 — c'est l'interface WEB, pas l'organe), puis "
                ":8767/mcp (200 mais sans champ d'etat : il annonce seulement que le "
                "SSE n'est pas implemente). L'organe repondait depuis le debut sur "
                ":8767/health. Deux fois j'ai conclu MUET sur ma propre sonde fausse — "
                "c'est le motif de la journee : distinguer 'il ne dit rien' de 'je ne "
                "sais pas ou ecouter'.",
    },
}

# ─── LES ONZE ORGANES INNERVES LE 2026-08-25 ────────────────────────────────
# Ils sortaient tous « VIVANT MAIS DENERVE » : ils fonctionnaient, mais on ne
# pouvait que leur prendre le pouls. Chacun expose en realite une interface ou il
# REPOND sur lui-meme — mesure faite port par port avant d'ecrire une seule ligne
# ici, parce que deux sondes fausses sur netcfg avaient deja suffi a le declarer
# muet a tort.
MEDIES.update({
    "NokidoWebHub": {"organe": "sens/interface", "url": "http://127.0.0.1:7400/health",
                     "champs": ("status", "version", "hub_port")},
    "NokidoDenoWebHub": {"organe": "SNC/bus", "url": "http://127.0.0.1:7401/health",
                         "champs": ("status", "version", "port", "backend")},
    "NokidoDenoHubMCP": {"organe": "SNC/transport", "url": "http://127.0.0.1:8769/health",
                         "champs": ("status", "version", "port", "tools_count")},
    "NokidoGoDispatcher": {"organe": "locomoteur/routage",
                           "url": "http://127.0.0.1:8779/health",
                           "champs": ("ok", "service")},
    "NokidoOpenAIProxy": {"organe": "metabolisme/ingress",
                          "url": "http://127.0.0.1:7777/health",
                          "champs": ("status", "service")},
    "NokidoAnthropicIngress": {"organe": "metabolisme/ingress",
                               "url": "http://127.0.0.1:7776/health",
                               "champs": ("status", "service")},
    "NokidoGeminiIngress": {"organe": "metabolisme/ingress",
                            "url": "http://127.0.0.1:7778/health",
                            "champs": ("status", "service")},
    "NokidoWebEgress": {"organe": "digestif/egress",
                        "url": "http://127.0.0.1:7779/health",
                        "champs": ("status", "service", "rag_threshold")},
    "NokidoNetcfgProxy": {"organe": "SNC/peripherique",
                          "url": "http://127.0.0.1:8767/health",
                          "champs": ("ok", "server", "version"), "accepte_401": True},
    # Temoignages NON JSON, acceptes tels quels : un organe n'a pas a parler notre
    # format pour prouver qu'il vit.
    "NokidoDenoProxy": {"organe": "SNC/transport", "url": "http://127.0.0.1:8000/health",
                        "champs": ("_texte",),
                        "note": "repond en texte brut (« Nokido Proxy Active »)."},
    "NokidoCaddyTLS": {"organe": "peau/terminaison", "url": "http://127.0.0.1:8443/",
                       "champs": ("_texte",), "codes_temoins": (400, 401, 403, 421, 502),
                       "note": "REFUS QUI TEMOIGNE : un 400 « Client sent an HTTP request "
                               "to an HTTPS server » PROUVE que Caddy est la et parle TLS. "
                               "Un terminateur absent ne repondrait rien du tout."},
})

_DECLARES: set[str] = set()


def _declarer(producteur: str, organe: str) -> None:
    """Declare la provenance UNE fois. La moelle refuse un producteur inconnu, et
    elle a raison : ingerer au jugement reviendrait a inventer sa provenance."""
    if producteur in _DECLARES or producteur in spine.REGISTRE:
        _DECLARES.add(producteur)
        return
    spine.declarer(spine.Provenance(
        producteur, organe, "epoch_s", "ts",
        note="pouls d'organe (forge_organ_afferent) — emis par l'organe, pas palpe"))
    _DECLARES.add(producteur)


def emettre(producteur: str, organe: str, mesures: dict,
            registre: str = "AFFERENT_DIRECT", kind: str = "pouls") -> tuple:
    """Un organe bat. Rend (ok, raison) — la raison est DITE quand ca ne passe pas.

    `registre` qualifie la nature du temoignage et VOYAGE avec lui : sans ca, un
    lecteur futur ne pourrait plus distinguer un pouls d'une prise de sang, et la
    distinction qu'on vient de payer serait reperdue au premier relais.
    """
    _declarer(producteur, organe)
    brut = dict(mesures)
    brut["ts"] = time.time()
    brut["registre"] = registre
    evt, raison = spine.ingerer(producteur, brut, kind=kind)
    if evt is None:
        return False, raison
    return (True, "") if spine.ecrire(evt) else (False, "ecriture refusee par la moelle")


def _interroger(url: str, timeout: float = 4.0, accepte_401: bool = False,
                codes_temoins: tuple = ()) -> tuple:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            brut = r.read().decode("utf-8", "replace")
        try:
            return json.loads(brut), ""
        except Exception:  # noqa: BLE001
            # TEMOIGNAGE NON JSON. Un organe qui repond « Nokido Proxy Active » a bel
            # et bien temoigne ; exiger du JSON pour l'entendre reviendrait a le
            # declarer muet parce qu'il ne parle pas notre dialecte.
            return {"_texte": brut.strip()[:120]}, ""
    except urllib.error.HTTPError as exc:
        if exc.code in codes_temoins:
            return {"_texte": "refus %d" % exc.code, "code": exc.code}, ""
        # UN REFUS EST UN TEMOIGNAGE. Un organe qui repond 401 prouve qu'il est la et
        # qu'il garde sa porte ; un organe absent ne repond rien du tout. Confondre
        # les deux, c'est declarer mort ce qui se contente d'etre ferme.
        if accepte_401 and exc.code in (401, 403):
            return {"status": "refus_authentifie", "code": exc.code}, ""
        return None, "HTTP %s" % exc.code
    except Exception as exc:  # noqa: BLE001
        return None, "%s" % type(exc).__name__


def battre_medies() -> dict:
    """Recueille le temoignage des organes qui ne savent pas ecrire dans la moelle.

    Rend un compte-rendu a TROIS etats par organe : `emis`, `muet` (l'organe n'a pas
    repondu — il est peut-etre arrete, ce qui est une information), `refuse` (la
    moelle a refuse l'evenement, et elle dit pourquoi).
    """
    rapport = {}
    for svc, spec in MEDIES.items():
        d, err = _interroger(spec["url"], accepte_401=bool(spec.get("accepte_401")),
                             codes_temoins=tuple(spec.get("codes_temoins") or ()))
        if d is None:
            rapport[svc] = {"etat": "muet", "raison": err}
            continue
        src = d.get("result", d) if isinstance(d, dict) else {}
        mesures = {}
        for champ in spec["champs"]:
            v = src.get(champ)
            if isinstance(v, list):
                v = len(v)                 # « combien de modeles », pas la liste
            if isinstance(v, dict):
                v = json.dumps(v)[:200]
            if v is not None:
                mesures[champ] = v
        if not mesures:
            rapport[svc] = {"etat": "muet",
                            "raison": "a repondu mais aucun champ attendu : %s"
                                      % ",".join(list(src)[:6])}
            continue
        ok, raison = emettre(svc, spec["organe"], mesures,
                             registre="AFFERENT_MEDIE", kind="temoignage")
        rapport[svc] = ({"etat": "emis", "mesures": mesures} if ok
                        else {"etat": "refuse", "raison": raison})
    return rapport


def dernier_pouls(producteur: str, fenetre_h: float = 24.0,
                  queue_octets: int = 4_000_000) -> tuple:
    """(age_s, raison). age_s vaut None quand l'organe n'a JAMAIS battu — ce qui
    n'est pas la meme chose qu'un battement ancien, ni qu'une moelle illisible.

    On lit le JOURNAL de la moelle, la ou `ecrire` depose. `relire` ne convient pas :
    il exige une AFFERENCE declaree, c'est-a-dire une source historique externe a
    rattraper — un pouls, lui, naît deja dans la moelle. Confondre les deux rendait
    « aucune afference declaree » sur un organe qui battait pourtant.
    """
    chemin = getattr(spine, "JOURNAL", None)
    if chemin is None:
        return None, "moelle sans journal declare"
    try:
        taille = chemin.stat().st_size
        with open(chemin, "rb") as fh:
            fh.seek(max(0, taille - queue_octets))
            brut = fh.read()
    except FileNotFoundError:
        return None, "journal de moelle absent — aucun organe n'a jamais battu"
    except Exception as exc:  # noqa: BLE001
        return None, "moelle illisible (%s)" % type(exc).__name__
    borne = time.time() - fenetre_h * 3600.0
    dernier = None
    for ligne in brut.split(b"\n"):
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            e = json.loads(ligne.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - muet-ok : 1re ligne coupee par la troncature
            continue
        if e.get("producteur") != producteur:
            continue
        ts = float(e.get("ts") or 0)
        if ts >= borne and (dernier is None or ts > dernier):
            dernier = ts
    if dernier is None:
        return None, "aucun battement sur %.0f h" % fenetre_h
    return time.time() - dernier, ""


def etat() -> dict:
    """Qui bat, qui se tait. Le denominateur est imprime, sinon « 0 muet » ne se
    distingue pas de « je n'ai pas su regarder »."""
    out = {"organes": {}, "interroges": len(MEDIES)}
    for svc in MEDIES:
        age, raison = dernier_pouls(svc)
        out["organes"][svc] = ({"bat_il_y_a_s": round(age, 1)} if age is not None
                               else {"silencieux": raison})
    return out


HEARTBEAT = ROOT / "sandbox" / "organ_afferent.heartbeat"


def boucle(intervalle_s: float = 300.0) -> int:
    """PERFUSION de la moelle. Sans cadence, un nerf est un fil sans influx.

    Mesure du 2026-08-25 qui a rendu cette boucle necessaire : `spine.collecter()`
    rendait `ingeres: 0` sur ses SEPT nerfs, tous en « raccordement au present ».
    L'afference n'etait pas cassee — elle etait positionnee a l'instant t et
    personne ne la re-derivait. Un appareil juste qui ne tourne jamais ne se
    distingue pas d'un appareil absent.

    Ce nerf ECRIT SON PROPRE HEARTBEAT : l'organe qui recueille les pouls des autres
    doit pouvoir etre juge par le meme contrat, sinon il s'exempte de la regle qu'il
    applique — et un juge hors contrat est exactement ce que cet audit combat.
    """
    import logging

    log = logging.getLogger("Nokido.Afferent")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    tour = 0
    # CADENCE DU BILAN. Un tour sur douze, soit ~1 h au rythme par defaut.
    # Pourquoi ici et pas ailleurs : le bilan consolide est reste INEXECUTABLE pendant
    # des semaines (NameError) sans que personne ne s'en apercoive, precisement parce
    # que rien ne le lancait regulierement. Un appareil de diagnostic qu'on ne declenche
    # qu'a la main ne signale sa propre panne a personne. On le raccroche donc au seul
    # organe dont le metier est de battre.
    tours_par_bilan = max(1, int(3600 // max(60.0, intervalle_s)))
    while True:
        debut = time.time()
        tour += 1
        # DEUX GESTES SEPARES (mesure 2026-08-25). Groupes dans un seul `try`, une
        # exception de `collecter()` effacait le compte rendu d'un `battre_medies()`
        # pourtant REUSSI : le journal disait « tour MANQUE » alors que quatre organes
        # avaient temoigne. Un echec en aval ne doit jamais rendre invisible un succes
        # en amont — c'est ainsi qu'on croit un organe muet alors qu'il parlait.
        try:
            rapport = battre_medies()
            emis = sum(1 for v in rapport.values() if v.get("etat") == "emis")
            muets = [k for k, v in rapport.items() if v.get("etat") == "muet"]
            log.info("[afferent] %d/%d organes ont temoigne%s", emis, len(rapport),
                     (" | MUETS: " + ",".join(muets)) if muets else "")
        except Exception as exc:  # noqa: BLE001
            log.warning("[afferent] recueil des temoignages MANQUE (%s: %s)",
                        type(exc).__name__, str(exc)[:120])
        try:
            recolte = spine.collecter()
            log.info("[afferent] moelle: %s ingeres, %s refuses",
                     recolte.get("ingeres"), recolte.get("refuses"))
        except Exception as exc:  # noqa: BLE001
            log.warning("[afferent] COLLECTE de la moelle manquee (%s: %s) — les nerfs "
                        "historiques ne progressent pas ce cycle", type(exc).__name__,
                        str(exc)[:120])
        if tour % tours_par_bilan == 1 or tours_par_bilan == 1:
            try:
                from nokido_agent.app.forge_health_diagnostic import run_cycle

                bilan = run_cycle()
                log.info("[afferent] BILAN de sante : score=%s/100, %d lacune(s)",
                         bilan.get("score"), len(bilan.get("gaps") or []))
                for _g in (bilan.get("gaps") or [])[:6]:
                    log.info("[afferent]   %s", str(_g)[:150])
            except Exception as exc:  # noqa: BLE001
                # Un bilan qui echoue doit CRIER : c'est exactement ce silence-la qui a
                # laisse `run_cycle` inexecutable sans que personne ne le sache.
                log.warning("[afferent] BILAN de sante IMPOSSIBLE (%s: %s) — le corps "
                            "n'a plus de mesure de lui-meme ce cycle",
                            type(exc).__name__, str(exc)[:140])
        # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`). Ce pouls s'ecrivait
        # en TEXTE BRUT (`str(time.time())`) : le contrat declare par
        # `service_loader.ts` est un fichier JSON, donc l'audit le lisait ILLISIBLE et
        # aucun pid n'y figurait. `beat_daemon` ne leve jamais mais RETOURNE False —
        # on garde le cri, un pouls non ecrit doit rester visible.
        from nokido_agent.app.forge_heartbeat import beat_daemon

        if not beat_daemon("organ_afferent"):
            log.warning("[afferent] propre heartbeat NON ecrit — ce nerf devient "
                        "lui-meme invisible au contrat")
        time.sleep(max(5.0, intervalle_s - (time.time() - debut)))


def _main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Nerf afferent des organes")
    ap.add_argument("--battre", action="store_true", help="un tour de recueil")
    ap.add_argument("--etat", action="store_true", help="qui bat, qui se tait")
    ap.add_argument("--boucle", action="store_true", help="perfusion continue")
    ap.add_argument("--intervalle", type=float, default=300.0)
    a = ap.parse_args(argv)
    if a.boucle:
        return boucle(a.intervalle)
    if a.battre or not a.etat:
        print(json.dumps(battre_medies(), ensure_ascii=False, indent=1))
    if a.etat:
        print(json.dumps(etat(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
