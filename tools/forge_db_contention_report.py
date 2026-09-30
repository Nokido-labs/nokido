# -*- coding: utf-8 -*-
"""tools/forge_db_contention_report.py — etat RUNTIME des bases, publiable.

NE PAS confondre avec une exposition du hub. Cet outil ne sert pas un port, il
PRODUIT un artefact en LECTURE SEULE : un pair distant (analyse externe, autre
agent, revue) obtient l'etat effectif des bases sans qu'aucune surface
d'execution ne soit ouverte. Publier un constat n'est pas ouvrir une porte.

CE QU'IL REPOND, et que le depot GitHub ne peut PAS dire :
  - quels chemins declares designent PHYSIQUEMENT le meme fichier ;
  - quels interrupteurs de bascule sont REELLEMENT actifs ;
  - quelle politique SQLite s'applique par base (journal, checkpoint, page) ;
  - quelle est la taille du WAL maintenant.

L'IDENTITE PHYSIQUE EST LA PROPRIETE DE PREMIER ORDRE, et c'est une mesure, pas
un principe. Le 2026-09-18, `V:` s'est revele etre un lecteur SUBSTITUE vers
`Nokido/RAG/` :

    %NOKIDO_DATA%\embeddings.db     dev=8967830048855926842 ino=281474976710724
    RAG/embeddings.db    dev=8967830048855926842 ino=281474976710724

Un seul fichier, un seul WAL, un seul verrou d'ecriture -- alors que la
comparaison des CHAINES rend False. Le faux negatif va dans le sens rassurant :
il fait conclure a une absence de contention qui existe. Un nom different n'est
pas une ressource differente ; jonctions, `subst`, liens, lecteurs reseau et
chemins relatifs produisent tous des alias.

CE QU'IL NE MESURE PAS, et qu'il DIT : la liste des connexions SQLite ouvertes
par les autres processus. Elle demanderait un handle par processus, que le compte
qui execute ce rapport n'a pas. Un champ absent est marque INCONNU, jamais zero.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/db : etat runtime des bases et de leur contention"

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# UN PRAGMA N'EST PAS L'AUTRE, et confondre les deux fait dire au rapport une
# chose FAUSSE sur la base. Mesure du 2026-09-18, sur ce rapport meme : il
# affichait `wal_autocheckpoint: 1000` pour la base RAG, ce qui se lit « la base
# est reglee a 1000 » -- alors que c'etait le DEFAUT DE MA PROPRE SONDE, ouverte
# en lecture seule. Ce reglage est PAR CONNEXION : chaque ecrivain porte le sien.
#
# PERSISTANTS : stockes dans le fichier, donc vrais pour tout le monde.
PRAGMAS_PERSISTANTS = ("journal_mode", "page_size", "auto_vacuum", "user_version")
# PAR CONNEXION : ce que MA sonde voit, et rien de plus. Les afficher sans le
# dire ferait conclure sur la politique des ecrivains, qu'on ne mesure pas ici.
PRAGMAS_DE_MA_SONDE = ("synchronous", "wal_autocheckpoint", "busy_timeout")
TABLES_SUIVIES = ("rag_chunks", "agent_messages", "task_queue", "access_switches",
                  "tasks", "lane_leases")


def _generifier(p: str) -> str:
    """Retire le profil utilisateur : un rapport se partage.

    Lecon du 2026-09-15 (generisation des chemins owner avant publication).
    """
    s = str(p)
    for base, jeton in ((str(ROOT), "<NOKIDO>"), (str(Path.home()), "<HOME>")):
        s = s.replace(base, jeton).replace(base.replace("\\", "/"), jeton)
    return s.replace("\\", "/")


# CHEMINS GOUVERNES PAR L'ENVIRONNEMENT — et l'environnement de ce rapport N'EST
# PAS celui des services. Mesure du 2026-09-18, sur ce rapport meme : il a
# annonce « CONTENTION : rag, access_switches » parce que le compte qui
# l'executait n'a pas `LAFORGE_SWITCHES_DB_PATH`. Or `services.toml:197` la pose
# pour le service : le hub, lance par le superviseur, utilise BIEN la base
# dediee. Le rapport decrivait son propre bac en le prenant pour le systeme.
#
# Un service n'herite du TOML que lance PAR LE SUPERVISEUR (mesure du 2026-09-14).
# Donc : nommer l'environnement mesure, et dire pour chaque chemin D'OU il vient.
ENV_DE_CHEMIN = {
    "rag": "LAFORGE_DB",
    "m2m": "LAFORGE_M2M_DB_PATH",
    "task_queue": "LAFORGE_TASKS_DB_PATH",
    "access_switches": "LAFORGE_SWITCHES_DB_PATH",
}


def _environnement() -> dict:
    """QUI mesure, et avec quelles variables — sans quoi le verdict est local."""
    import getpass

    pose = {v: bool(os.environ.get(v)) for v in ENV_DE_CHEMIN.values()}
    manquantes = sorted(v for v, p in pose.items() if not p)
    return {
        "compte": getpass.getuser(),
        "variables_de_chemin_posees": pose,
        "AVERTISSEMENT": (
            "Ce rapport decrit l'environnement qui l'EXECUTE. Les variables "
            "absentes ici (%s) peuvent etre posees pour les SERVICES via "
            "proxy_deno/core/services.toml -- un service n'herite du TOML que "
            "lance par le superviseur. Un verdict de contention tire d'ici ne "
            "vaut donc PAS pour le hub : le verifier dans le TOML avant de "
            "conclure." % (", ".join(manquantes) or "aucune")
        ) if manquantes else "toutes les variables de chemin sont posees ici",
    }


def _bases_declarees() -> dict:
    """Les chemins tels que le CODE les resout, pas tels qu'on les suppose."""
    from app import forge_db_path as dbp

    out = {
        "rag": dbp.db_path(),
        "m2m": dbp.m2m_path(),
        "task_queue": dbp.tasks_path(),
    }
    try:
        from app.forge_access_switches import DEFAULT_DB_PATH

        out["access_switches"] = str(DEFAULT_DB_PATH)
    except Exception as e:  # noqa: BLE001
        out["access_switches"] = "INCONNU (%s)" % type(e).__name__
    return out


def _interrupteurs() -> dict:
    from app import forge_db_path as dbp

    return {
        "m2m": {"actif": dbp.m2m_switch_actif(),
                "fichier": _generifier(dbp._M2M_SWITCH),
                "pose": dbp._M2M_SWITCH.exists()},
        "task_queue": {"actif": dbp.tasks_switch_actif(),
                       "fichier": _generifier(dbp._TASKS_SWITCH),
                       "pose": dbp._TASKS_SWITCH.exists()},
    }


def _identite(chemins: dict) -> dict:
    """Regroupe les chemins qui designent LE MEME fichier physique.

    C'est le coeur du rapport. On n'oppose pas des chaines : on lit `st_dev` et
    `st_ino`, seuls capables de voir a travers un alias.
    """
    groupes: dict = {}
    inconnus = []
    for nom, p in chemins.items():
        try:
            st = os.stat(p)
            cle = "%s:%s" % (st.st_dev, st.st_ino)
        except OSError as e:
            inconnus.append({"nom": nom, "chemin": _generifier(p),
                             "raison": type(e).__name__})
            continue
        groupes.setdefault(cle, []).append(nom)
    partages = {k: v for k, v in groupes.items() if len(v) > 1}
    return {
        "groupes_physiques": {k: sorted(v) for k, v in groupes.items()},
        "PARTAGENT_LE_MEME_FICHIER": {k: sorted(v) for k, v in partages.items()},
        "verdict": ("PARTAGE DANS CET ENVIRONNEMENT : %s — verifier services.toml "
                    "avant d'en conclure a une contention du hub"
                    % "; ".join(", ".join(v) for v in partages.values())
                    if partages else "aucune base declaree n'en partage une autre"),
        "non_mesurables": inconnus,
    }


def _etat_base(chemin: str) -> dict:
    p = Path(chemin)
    d = {"chemin": _generifier(chemin), "existe": p.exists()}
    if not p.exists():
        d["note"] = "ABSENT (pas un zero : la base n'a pas encore ete creee)"
        return d
    st = p.stat()
    d["taille_Mo"] = round(st.st_size / 2**20, 1)
    d["dev"], d["ino"] = st.st_dev, st.st_ino
    for suffixe in ("-wal", "-shm"):
        f = Path(chemin + suffixe)
        d["wal_Mo" if suffixe == "-wal" else "shm_Ko"] = (
            round(f.stat().st_size / (2**20 if suffixe == "-wal" else 2**10), 2)
            if f.exists() else 0.0)
    try:
        # Lecture SEULE, et aucune requete d'agregat : un COUNT sur une base de
        # 25 Go a deja couche le hub (six fois). On lit sqlite_master et les PRAGMA.
        con = sqlite3.connect("file:%s?mode=ro" % chemin.replace("\\", "/"), uri=True)
        try:
            d["pragmas_persistants"] = {
                k: con.execute("PRAGMA %s" % k).fetchone()[0] for k in PRAGMAS_PERSISTANTS
            }
            d["pragmas_de_ma_sonde"] = {
                k: con.execute("PRAGMA %s" % k).fetchone()[0] for k in PRAGMAS_DE_MA_SONDE
            }
            d["_avertissement_pragmas"] = (
                "`pragmas_de_ma_sonde` decrit CETTE connexion en lecture seule, PAS "
                "la politique des ecrivains : ces reglages sont par connexion. La "
                "politique reelle se lit dans les portes d'ecriture "
                "(`forge_db_path.open_writer`, `forge_db._PRAGMAS_RW`)."
            )
            noms = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            d["tables_suivies_presentes"] = sorted(n for n in TABLES_SUIVIES if n in noms)
            d["tables_total"] = len(noms)
        finally:
            con.close()
    except sqlite3.Error as e:
        d["pragmas_persistants"] = "ILLISIBLE (%s)" % str(e)[:60]
    return d


def rapport() -> dict:
    import datetime

    chemins = _bases_declarees()
    lisibles = {k: v for k, v in chemins.items() if not str(v).startswith("INCONNU")}
    return {
        "genere": datetime.datetime.now().isoformat(timespec="seconds"),
        "environnement": _environnement(),
        "interrupteurs": _interrupteurs(),
        "identite_physique": _identite(lisibles),
        "bases": {k: _etat_base(v) for k, v in lisibles.items()},
        "non_mesure": [
            "connexions SQLite ouvertes par les AUTRES processus : demande un "
            "handle par processus, que le compte executant n'a pas. INCONNU, pas zero.",
            "debit d'ecriture par base : demande un echantillonnage dans le temps, "
            "pas un instantane.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="sortie JSON brute")
    ap.add_argument("--sortie", default=None, help="ecrire dans un fichier")
    a = ap.parse_args()
    r = rapport()
    texte = json.dumps(r, ensure_ascii=False, indent=1, default=str)
    if not a.json:
        e = r["environnement"]
        lignes = ["# Etat runtime des bases Nokido", "",
                  "genere : %s" % r["genere"],
                  "compte mesure : %s" % e["compte"], ""]
        lignes.append("## Environnement de la mesure")
        lignes.append("")
        lignes.append(e["AVERTISSEMENT"])
        lignes.append("")
        lignes.append("## Identite physique")
        lignes.append("")
        lignes.append("VERDICT : %s" % r["identite_physique"]["verdict"])
        lignes.append("")
        lignes.append("## Interrupteurs")
        for nom, i in r["interrupteurs"].items():
            lignes.append("- %-12s actif=%s pose=%s" % (nom, i["actif"], i["pose"]))
        lignes.append("")
        lignes.append("## Bases")
        for nom, b in r["bases"].items():
            if not b.get("existe"):
                lignes.append("- %-12s %s" % (nom, b.get("note", "absent")))
                continue
            lignes.append("- %-12s %8.1f Mo  wal=%5.2f Mo  ino=%s" % (
                nom, b["taille_Mo"], b["wal_Mo"], b["ino"]))
            lignes.append("    %s" % b["chemin"])
            lignes.append("    persistants : %s" % b.get("pragmas_persistants"))
            lignes.append("    (ma sonde)  : %s  <- par CONNEXION, pas la politique des ecrivains"
                          % b.get("pragmas_de_ma_sonde"))
            lignes.append("    tables suivies : %s" % (b.get("tables_suivies_presentes") or "aucune"))
        lignes.append("")
        lignes.append("## NON MESURE (dit, jamais range du cote sain)")
        for n in r["non_mesure"]:
            lignes.append("- %s" % n)
        texte = "\n".join(lignes)
    if a.sortie:
        Path(a.sortie).write_text(texte, encoding="utf-8")
        print("ecrit :", _generifier(a.sortie))
    else:
        print(texte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
