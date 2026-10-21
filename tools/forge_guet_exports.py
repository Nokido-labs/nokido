"""Guet UNIQUE des exports officiels de conversations (Claude claude.ai, ChatGPT ; Google Takeout mis de cote).

- detection par le CONTENU du zip (jamais par son nom) ;
- decompression dans un dossier DATE (`<racine>/exports_conversations/<type>/<date>_<empreinte8>/`) ;
- indexation au fil de l'eau, insertion par lots (forge_conv_exports) ;
- etat par EMPREINTE sha256 du zip : un export deja traite ne l'est pas deux fois ; un echec se DIT et se rejoue.
Chaque export contient tout l'historique : la deduplication (INSERT OR IGNORE, id = sha256 source+texte) ignore
l'existant -- verifiee dans forge_conv_indexer._insert_chunks le 14/10.
Tourne SOUS LE COMPTE OWNER (tache planifiee interactive, comme Nokido-ConvIndex) : les comptes du hub ne lisent
pas Telechargements.

    python tools/forge_guet_exports.py [--telechargements DIR] [--sortie DIR] [--etat FICHIER]
"""
from __future__ import annotations

__FORGE_COLOR__ = 'digestif/ingestion : guet unique des exports officiels de conversations (zip reconnus par le contenu, indexation idempotente)'

import json
import time
import zipfile
from pathlib import Path


def empreinte(chemin: Path) -> str:
    from nokido_agent.app.forge_utils import sha256_fichier  # noqa: PLC0415 -- corps partage (cliquet clones, 18/10)

    return sha256_fichier(chemin)


def membre_conversations(z: zipfile.ZipFile) -> tuple[str, str | None]:
    """(plateforme, membre) -- par le CONTENU : `conversations.json` d'abord, sinon tout `.json` du zip ;
    Takeout reconnu a son arborescence et MIS DE COTE (format a lire sur un vrai export)."""
    noms = z.namelist()
    if any(n.startswith("Takeout/") for n in noms):
        return "takeout", None
    candidats = sorted((n for n in noms if n.lower().endswith(".json")),
                       key=lambda n: n.rsplit("/", 1)[-1] != "conversations.json")
    for n in candidats:
        with z.open(n) as fh:
            tete = fh.read(1 << 16).decode("utf-8", "replace")
        if '"chat_messages"' in tete:
            return "claude", n
        if '"mapping"' in tete:
            return "chatgpt", n
        if '"responses"' in tete and ('"conversations"' in tete or '"conversation"' in tete):
            return "grok", n
    return "INCONNU", None


def structure_takeout(z: zipfile.ZipFile) -> dict:
    """FORME d'un export Google Takeout, jamais son contenu (18/10) : nombre de membres, extensions, dossiers des
    3 premiers niveaux, membres Gemini/Bard et leur taille. Le guet tourne sous le compte owner -- le hub n'a pas
    acces aux Telechargements -- c'est donc a lui de consigner la forme reelle sur laquelle ecrire l'analyseur."""
    infos = z.infolist()
    ext, dossiers = {}, {}
    for i in infos:
        e = Path(i.filename).suffix
        ext[e] = ext.get(e, 0) + 1
        d = "/".join(Path(i.filename).parts[:3])
        dossiers[d] = dossiers.get(d, 0) + 1
    gemini = sorted([i.filename, i.file_size] for i in infos
                    if "gemini" in i.filename.lower() or "bard" in i.filename.lower())
    return {"membres": len(infos), "extensions": ext, "dossiers": dossiers, "gemini": gemini[:50],
            "gemini_omis": max(0, len(gemini) - 50)}


def traiter(zip_path: Path, racine_sortie: Path, etat: dict, indexer, inserer) -> dict:
    """Un zip -> verdict ecrit dans `etat` (cle = empreinte). Ne leve jamais : un echec est un verdict."""
    emp = empreinte(zip_path)
    # Verdicts TERMINAUX : seul un ECHEC (zip tronque, telechargement en cours) se rejoue au passage suivant.
    # MIS_DE_COTE (Takeout) se rouvrira quand l'analyseur existera : purger alors ces entrees de l'etat.
    prec = etat.get(emp) or {}
    if prec.get("verdict") in ("INDEXE", "IGNORE") or (prec.get("verdict") == "MIS_DE_COTE" and "structure" in prec):
        return etat[emp]
    if prec.get("verdict") == "MIS_DE_COTE":  # entree d'avant le 18/10 : on complete sa structure, rien d'autre
        try:
            with zipfile.ZipFile(zip_path) as z:
                prec["structure"] = structure_takeout(z)
        except Exception as e:  # noqa: BLE001 -- structure illisible : dite, l'entree reste mise de cote
            prec["structure"] = {"illisible": "%s: %s" % (type(e).__name__, str(e)[:120])}
        etat[emp] = prec
        return prec
    v = {"zip": zip_path.name, "vu_le": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        with zipfile.ZipFile(zip_path) as z:
            t, membre = membre_conversations(z)
            v["type"] = t
            if t in ("INCONNU", "takeout"):
                v["verdict"] = "MIS_DE_COTE" if t == "takeout" else "IGNORE"
                if t == "takeout":
                    v["structure"] = structure_takeout(z)
                v["raison"] = ("format Takeout a lire sur un vrai export avant tout analyseur" if t == "takeout"
                               else "ni chat_messages ni mapping : pas un export de conversations connu")
                etat[emp] = v
                return v
            dest = racine_sortie / t / ("%s_%s" % (time.strftime("%Y-%m-%d"), emp[:8]))
            dest.mkdir(parents=True, exist_ok=True)
            z.extract(membre, dest)
        v["dossier"] = str(dest)
        v["compte"] = indexer(dest / membre, inserer)
        v["verdict"] = "INDEXE"
    except Exception as e:  # noqa: BLE001 -- un zip tronque (telechargement en cours) se rejoue au passage suivant
        v.update(verdict="ECHEC", raison="%s: %s" % (type(e).__name__, str(e)[:200]))
    etat[emp] = v
    return v


def passage(telechargements: Path, racine_sortie: Path, fichier_etat: Path, indexer, inserer,
            age_min_s: float = 120.0) -> list:
    """Un passage du guet : zips assez anciens (telechargement fini), non encore INDEXES."""
    try:
        etat = json.loads(fichier_etat.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        etat = {}
    verdicts = []
    # Pre-filtre (nom, taille, mtime) -> empreinte deja calculee : un passage horaire ne re-hache pas tout
    # Telechargements (des zips de plusieurs Go y dorment) ; l'empreinte reste la cle de verite.
    connus = etat.setdefault("_signatures", {})
    for z in sorted(telechargements.glob("*.zip"), key=lambda p: p.stat().st_mtime):
        st = z.stat()
        if time.time() - st.st_mtime < age_min_s:
            continue
        sig = "%s|%d|%d" % (z.name, st.st_size, int(st.st_mtime))
        emp = connus.get(sig)
        prec = etat.get(emp) or {} if emp else {}
        if emp and (prec.get("verdict") in ("INDEXE", "IGNORE")
                    or (prec.get("verdict") == "MIS_DE_COTE" and "structure" in prec)):
            continue  # une MIS_DE_COTE sans structure (avant le 18/10) passe par traiter pour la completer
        v = traiter(z, racine_sortie, etat, indexer, inserer)
        connus[sig] = next((k for k, x in etat.items() if x is v), None) or emp
        verdicts.append(v)
    fichier_etat.parent.mkdir(parents=True, exist_ok=True)
    fichier_etat.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    return verdicts


def main(argv=None) -> int:
    """Point d'entree de la tache planifiee : branche l'insertion REELLE (forge_conv_indexer._insert_chunks,
    qui caviarde et deduplique par contenu) -- aucune insertion parallele n'est reecrite ici."""
    import argparse
    import sys

    racine = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="guet des exports officiels de conversations")
    ap.add_argument("--telechargements", default=str(Path.home() / "Downloads"))
    ap.add_argument("--sortie", default=str(racine / "sandbox" / "exports_conversations"))
    ap.add_argument("--etat", default=str(racine / "sandbox" / "guet_exports_etat.json"))
    a = ap.parse_args(argv)
    sys.path[:0] = [str(racine / "app"), str(racine / "tools"), str(racine)]
    import forge_conv_exports as fx
    from forge_conv_indexer import _insert_chunks

    verdicts = passage(Path(a.telechargements), Path(a.sortie), Path(a.etat), fx.indexer_export, _insert_chunks)
    for v in verdicts:
        print("[guet] %s : %s%s" % (v.get("zip"), v.get("verdict"),
                                    (" -- " + v["raison"]) if v.get("raison") else ""))
    print("[guet] %d zip(s) examine(s)" % len(verdicts))
    return 1 if any(v.get("verdict") == "ECHEC" for v in verdicts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
