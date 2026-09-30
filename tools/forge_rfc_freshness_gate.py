"""Gate de FRAICHEUR des RFC ingerees : le corpus local vs l'etat amont IETF.

`audit_rfc_compliance` certifie la PRESENCE (36/36, 2582 chunks). Il ne dit rien
de la FRAICHEUR : une RFC remplacee en amont y reste cochee. Une norme obsolete
citee comme autorite est pire qu'une norme absente -- l'absence se voit, la
peremption non.

AMONT. On lit `rfc-index.xml` de rfc-editor.org : c'est la source NORMATIVE des
relations `obsoleted-by` / `updated-by`, celle dont datatracker est le frontend.
Un seul GET pour tout le corpus, la ou l'API par document en demanderait un par
RFC -- 36 appels reseau pour la meme information.

TROIS ETATS, JAMAIS DEUX. Un amont injoignable rend `AMONT_INJOIGNABLE`, jamais
`A_JOUR` : conclure d'une source qui se tait est le defaut que ce depot paie le
plus souvent. Le code de sortie distingue les deux (2 = verdict, 3 = pas pu
regarder), pour qu'un gate ne passe pas au vert sur un reseau coupe.

RESEAU. Le compte par defaut n'a pas d'egress : lancer avec `network=true`
(LaForgeSbxOnline) ou `run_job online=true`, sinon le gate sortira en 3.

Usage :
    python tools/forge_rfc_freshness_gate.py            # obsoletes = echec
    python tools/forge_rfc_freshness_gate.py --strict   # + les "updated by"
    python tools/forge_rfc_freshness_gate.py --json     # sortie machine
"""

__FORGE_COLOR__ = "immunitaire/conformite-normative"

import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INDEX_URL = "https://www.rfc-editor.org/rfc-index.xml"
# Le namespace est en HTTPS dans le document servi ("https://www.rfc-editor.org/
# rfc-index"). L'ecrire en http fait echouer TOUS les findall en silence : 36/36
# ressortaient « INCONNUE_AMONT », y compris la RFC 791. On le lit donc sur la
# racine plutot que de le supposer -- un namespace suppose est une constante qui
# ment le jour ou l'amont change de schema.
NS = {"r": "https://www.rfc-editor.org/rfc-index"}
RAPPORT = ROOT / "docs" / "RFC_FRESHNESS.md"
JSON_OUT = ROOT / "sandbox" / "rfc_freshness.json"
TIMEOUT = 60


def _rfcs_ingerees():
    """Les RFC que le corpus declare porter, par categorie.

    Reutilise `CRITICAL_RFCS` d'`audit_rfc_compliance` : la liste ciblee vit la,
    et la dupliquer ici garantirait qu'elles divergent.
    """
    from nokido_agent.tools.audit_rfc_compliance import CRITICAL_RFCS

    out = []
    for categorie, entrees in CRITICAL_RFCS.items():
        for e in entrees:
            num = "".join(ch for ch in e if ch.isdigit())
            if num:
                out.append((categorie, e.strip(), int(num)))
    return out


def _amont(url=INDEX_URL):
    """Rend (relations, erreur). `relations` est None si on n'a PAS pu regarder."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:  # noqa: S310
            brut = r.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, "%s: %s" % (type(e).__name__, e)
    try:
        racine = ET.fromstring(brut)
    except ET.ParseError as e:
        return None, "ParseError: %s" % e

    # Namespace LU sur la racine, jamais suppose.
    ns = {"r": racine.tag.split("}")[0][1:]} if racine.tag.startswith("{") else {"r": ""}
    globals()["NS"] = ns

    rel = {}
    for entree in racine.findall("r:rfc-entry", ns):
        doc = entree.findtext("r:doc-id", default="", namespaces=ns).strip()
        m = re.match(r"RFC0*(\d+)$", doc)
        if not m:
            continue
        num = int(m.group(1))

        def _refs(balise, _e=entree, _ns=ns):
            n = _e.find("r:%s" % balise, _ns)
            if n is None:
                return []
            return [int(re.sub(r"\D", "", d.text or "") or 0)
                    for d in n.findall("r:doc-id", _ns) if (d.text or "").strip()]

        rel[num] = {
            "statut": entree.findtext("r:current-status", default="",
                                      namespaces=ns).strip(),
            "obsoleted_by": [n for n in _refs("obsoleted-by") if n],
            "updated_by": [n for n in _refs("updated-by") if n],
        }
    return rel, None


def evaluer(strict=False, url=INDEX_URL):
    """Confronte le corpus a l'amont. Ne conclut jamais depuis un silence."""
    cibles = _rfcs_ingerees()
    rel, err = _amont(url)
    if rel is None:
        return {"etat": "AMONT_INJOIGNABLE", "raison": err,
                "cibles": len(cibles), "verdicts": [], "strict": strict}

    verdicts = []
    for categorie, libelle, num in cibles:
        info = rel.get(num)
        if info is None:
            verdicts.append({"rfc": libelle, "num": num, "categorie": categorie,
                             "verdict": "INCONNUE_AMONT",
                             "detail": "absente de l'index rfc-editor"})
            continue
        if info["obsoleted_by"]:
            verdicts.append({"rfc": libelle, "num": num, "categorie": categorie,
                             "verdict": "OBSOLETE", "statut": info["statut"],
                             "remplacee_par": info["obsoleted_by"]})
        elif info["updated_by"]:
            verdicts.append({"rfc": libelle, "num": num, "categorie": categorie,
                             "verdict": "MISE_A_JOUR", "statut": info["statut"],
                             "mise_a_jour_par": info["updated_by"]})
        else:
            verdicts.append({"rfc": libelle, "num": num, "categorie": categorie,
                             "verdict": "A_JOUR", "statut": info["statut"]})

    compte = {}
    for v in verdicts:
        compte[v["verdict"]] = compte.get(v["verdict"], 0) + 1
    # GARDE D'INSTRUMENT. Si l'amont repond mais que RIEN ne s'apparie, c'est le
    # parseur qui est faux, pas le corpus qui est inconnu. Mesure 2026-09-03 :
    # un namespace en http au lieu de https rendait 36/36 « INCONNUE_AMONT »,
    # RFC 791 comprise. Une absence massive et uniforme est un symptome
    # d'instrument, jamais un verdict.
    if cibles and compte.get("INCONNUE_AMONT", 0) == len(cibles):
        return {"etat": "INSTRUMENT_SUSPECT", "cibles": len(cibles),
                "raison": "aucune des %d cibles appariee alors que l'amont a "
                          "repondu (%d entrees lues) : parseur ou schema amont "
                          "a verifier" % (len(cibles), len(rel)),
                "verdicts": [], "compte": compte, "strict": strict}
    return {"etat": "MESURE", "source_amont": url, "cibles": len(cibles),
            "verdicts": verdicts, "compte": compte, "strict": strict}


def _ecrire(chemin, texte):
    """Ecrit, ou rend le chemin de repli. Le verdict ne meurt pas sur l'ACL.

    Mesure 2026-09-03 : `docs/` n'est pas ecrivable par le compte sandbox, et le
    gate tombait en PermissionError APRES avoir calcule son verdict -- une mesure
    juste perdue pour une ecriture secondaire.
    """
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(texte, encoding="utf-8")
        return chemin, None
    except OSError as e:
        repli = ROOT / "sandbox" / chemin.name
        try:
            repli.parent.mkdir(parents=True, exist_ok=True)
            repli.write_text(texte, encoding="utf-8")
            return repli, "%s non ecrivable (%s) — repli" % (chemin, type(e).__name__)
        except OSError as e2:
            return None, "ni %s ni %s (%s)" % (chemin, repli, type(e2).__name__)


def _rapport(res):
    lignes = ["# Fraicheur des RFC ingerees", ""]
    if res["etat"] != "MESURE":
        lignes += ["**%s** — %s" % (res["etat"], res.get("raison", "?")), "",
                   "Ce n'est PAS un verdict de conformite : rien n'a pu etre",
                   "compare. Relancer avec `network=true`.", ""]
        return _ecrire(RAPPORT, "\n".join(lignes))
    c = res["compte"]
    lignes += ["Amont : `%s` (source normative des relations Obsoletes/Updates)."
               % res["source_amont"], "",
               "| verdict | n |", "|---|---|"]
    for k in ("A_JOUR", "MISE_A_JOUR", "OBSOLETE", "INCONNUE_AMONT"):
        lignes.append("| %s | %d |" % (k, c.get(k, 0)))
    lignes.append("")
    for etiquette, titre in (("OBSOLETE", "## Obsoletes — a re-ingerer"),
                             ("MISE_A_JOUR", "## Mises a jour par un texte plus recent"),
                             ("INCONNUE_AMONT", "## Inconnues de l'amont")):
        lot = [v for v in res["verdicts"] if v["verdict"] == etiquette]
        if not lot:
            continue
        lignes += [titre, ""]
        for v in lot:
            sup = v.get("remplacee_par") or v.get("mise_a_jour_par") or []
            lignes.append("- **%s** (%s)%s" % (
                v["rfc"], v["categorie"],
                " -> RFC %s" % ", ".join(str(n) for n in sup) if sup else ""))
        lignes.append("")
    return _ecrire(RAPPORT, "\n".join(lignes))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv
    res = evaluer(strict=strict)

    ou_json, av_json = _ecrire(JSON_OUT, json.dumps(res, indent=1,
                                                    ensure_ascii=False))
    ou_md, av_md = _rapport(res)
    for av in (av_json, av_md):
        if av:
            print("[rfc-freshness] %s" % av, file=sys.stderr)

    if "--json" in argv:
        print(json.dumps(res.get("compte", {"etat": res["etat"]}),
                         ensure_ascii=False))
    if res["etat"] != "MESURE":
        print("[rfc-freshness] AMONT INJOIGNABLE (%s) — aucun verdict rendu ; "
              "relancer avec network=true" % res.get("raison"), file=sys.stderr)
        return 3

    c = res["compte"]
    print("[rfc-freshness] %d ciblee(s) : %d a jour, %d mises a jour, "
          "%d obsoletes, %d inconnues de l'amont"
          % (res["cibles"], c.get("A_JOUR", 0), c.get("MISE_A_JOUR", 0),
             c.get("OBSOLETE", 0), c.get("INCONNUE_AMONT", 0)))
    for v in res["verdicts"]:
        if v["verdict"] == "OBSOLETE":
            print("   OBSOLETE  %-9s -> RFC %s" % (
                v["rfc"], ", ".join(str(n) for n in v["remplacee_par"])))
        elif strict and v["verdict"] == "MISE_A_JOUR":
            print("   MAJ       %-9s -> RFC %s" % (
                v["rfc"], ", ".join(str(n) for n in v["mise_a_jour_par"])))
    print("rapport : %s" % (ou_md or "NON ECRIT"))
    print("json    : %s" % (ou_json or "NON ECRIT"))
    if c.get("OBSOLETE"):
        return 2
    if strict and c.get("MISE_A_JOUR"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
