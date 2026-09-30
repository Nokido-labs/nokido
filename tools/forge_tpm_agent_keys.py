"""forge_tpm_agent_keys.py — provisionne les cles TPM PAR AGENT (geste owner).

__FORGE_COLOR__ = 'identite/cles'

POURQUOI CET OUTIL (mesure du 2026-09-20)
=========================================

`forge_persona_tpm` sait deja tout faire : `_ALG = ECDSA_P256` (asymetrique),
`nom_cle_agent`, `ensure_agent_key`, `sign_as`, `verify_etat_agent`. Ce qui
manquait n'etait pas une capacite, c'etait le BON COMPTE.

Diagnostic pas a pas, depuis le compte du hub (`LaForgeSbxOffline`, non admin) :

    _ncrypt()                   OK
    _open_provider()            OK              le TPM repond
    flags sans MACHINE (0x40)   magasin UTILISATEUR du compte sandbox : VIDE
      OpenKey laforge-persona-sign   0x80090011 NTE_NOT_FOUND
    flags AVEC MACHINE (0x60)   FORGE_TPM_MACHINE=1
      OpenKey laforge-persona-sign   0x80090010 NTE_PERM      <- EXISTE, accces refuse
      CreatePersistedKey             0x00000000 OK            <- objet cree en memoire
      FinalizeKey                    0x80090010 NTE_PERM      <- PERSISTANCE refusee

`NTE_PERM` et non `NTE_NOT_SUPPORTED` : le TPM accepte l'algorithme et le nom,
c'est l'ECRITURE dans le magasin MACHINE qui exige l'elevation. La creation est
donc un geste ADMINISTRATEUR, a lancer dans une console admin HORS de l'agent --
exactement comme le relancement du hub.

CONFORMITE (directive owner : « respecte les RFC »)
===================================================

  * Une cle par IDENTITE declaree au registre, jamais par etiquette libre.
    `nom_cle_agent` REFUSE tout nom absent du SSoT : donner du materiel
    cryptographique a un nom inconnu, c'est authentifier un fantome.
  * ECDSA P-256, cle privee non exportable, generee et gardee par le TPM.
    C'est ce que RFC 7515/7518 (JWS/ES256) attendent d'une signature, et ce que
    RFC 9449 (DPoP) suppose d'une preuve de possession.
  * RFC 6749 §2.2 : l'identifiant designe UN enregistrement. Le garde
    `test_registre_identite_unicite_nr` verrouille cette unicite en amont.

⚠️ CE QUE CES CLES NE DONNENT PAS. `NCRYPT_MACHINE_KEY_FLAG` : ce sont des cles
MACHINE. Elles empechent l'usurpation ACCIDENTELLE, tracent l'origine et
survivent au redemarrage -- mais un process ELEVE du meme hote peut les invoquer.
C'est une ATTRIBUTION forte, PAS une isolation inter-process. Le dire est le
minimum : « invoquer une RFC qu'on n'implemente pas est une fausse garantie ».

USAGE
=====
    LAFORGE_PYTHON tools/forge_tpm_agent_keys.py --check          # etat, sans rien ecrire
    LAFORGE_PYTHON tools/forge_tpm_agent_keys.py --list           # agents M2M actifs
    LAFORGE_PYTHON tools/forge_tpm_agent_keys.py --create CLAUDE ANTIGRAVITY
    LAFORGE_PYTHON tools/forge_tpm_agent_keys.py --create-actifs   # les agents mesures

`--check` et `--list` sont SANS EFFET et se lancent depuis n'importe quel compte.
`--create*` exige une console ADMIN : sans elle, l'outil le DIT et s'arrete au
lieu d'echouer en silence.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

# Agents REELLEMENT actifs en M2M, mesures le 2026-09-20 sur `agent_messages`
# (21 852 lignes). On ne provisionne pas 146 identites « au cas ou » : une cle
# non utilisee est une surface, pas une securite.
AGENTS_ACTIFS = ("CLAUDE", "ANTIGRAVITY", "GEMINI", "SUPERVISOR",
                 "TASK_EXECUTOR", "WORKER_CODE", "HUB")


def _est_admin() -> bool | None:
    """True/False, ou None si ILLISIBLE. On ne repond pas `False` a une absence
    de mesure -- c'est la distinction que tout ce depot defend."""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return None


# Alias SDDL courants -- une ACL qui n'est lisible que par un expert n'informe
# personne. Table volontairement courte : ce qu'on ne sait pas nommer est
# affiche tel quel plutot que devine.
_SIDS_COURTS = {
    "BA": "BUILTIN\\Administrateurs", "SY": "NT AUTHORITY\\SYSTEM",
    "WD": "Tout le monde", "AU": "Utilisateurs authentifies",
    "BU": "BUILTIN\\Utilisateurs", "LS": "NT AUTHORITY\\LOCAL SERVICE",
    "NS": "NT AUTHORITY\\NETWORK SERVICE", "CO": "CREATOR OWNER",
}


def _nom_du_sid(sid: str) -> str:
    """Nom lisible d'un SID, ou le motif de l'echec -- jamais un nom invente."""
    try:
        import ctypes
        from ctypes import wintypes
        adv = ctypes.windll.advapi32
        psid = ctypes.c_void_p()
        if not adv.ConvertStringSidToSidW(sid, ctypes.byref(psid)):
            return "(SID non convertible)"
        nom = ctypes.create_unicode_buffer(256)
        dom = ctypes.create_unicode_buffer(256)
        cb_n, cb_d = wintypes.DWORD(256), wintypes.DWORD(256)
        use = wintypes.DWORD()
        ok = adv.LookupAccountSidW(None, psid, nom, ctypes.byref(cb_n),
                                   dom, ctypes.byref(cb_d), ctypes.byref(use))
        ctypes.windll.kernel32.LocalFree(psid)
        if not ok:
            return "(SID inconnu de cette machine)"
        return "%s\\%s" % (dom.value, nom.value) if dom.value else nom.value
    except Exception as e:                                # noqa: BLE001
        return "(resolution impossible : %s)" % type(e).__name__


def _etat_cle(agent: str) -> tuple:
    """(agent, nom_cle, etat, detail). TROIS etats, jamais un booleen."""
    from nokido_agent.app.forge_persona_tpm import (
        etat_cle_tpm, nom_cle_agent, sign_as, verify_etat_agent)

    try:
        nom = nom_cle_agent(agent)
    except ValueError as exc:
        return agent, None, "NON_DECLARE", str(exc)[:90]
    sig = sign_as(agent, b"sonde-etat")
    if sig:
        verdict, raison = verify_etat_agent(agent, b"sonde-etat", sig)
        if verdict == "VALIDE":
            return agent, nom, "UTILISABLE", "signe et verifie (%d o)" % len(sig)
        return agent, nom, "SIGNE_NON_VERIFIE", "%s : %s" % (verdict, raison[:60])
    # PAS DE SIGNATURE : reste a dire POURQUOI. `INDISPONIBLE` fusionnait
    # « la cle n'existe pas » et « acces refuse », qui appellent des gestes
    # OPPOSES -- provisionner, ou ouvrir un acces. La distinction existe cote
    # Windows ; on la demande au lieu de la perdre (mesure du 2026-09-21).
    etat, code = etat_cle_tpm(nom)
    detail = {
        "ABSENTE": "la cle n'existe pas dans ce magasin (rc=0x%08X) — "
                   "provisionner, ce n'est pas un probleme de droits",
        "REFUSEE": "la cle EXISTE mais ce compte ne peut pas l'ouvrir "
                   "(rc=0x%08X) — droits, pas provisionnement",
        "UTILISABLE": "ouverte sans signer (rc=0x%08X) — la cle repond mais la "
                      "signature a echoue : instruire, ne pas provisionner",
    }.get(etat, "code NCrypt non classe (rc=0x%08X) — INDETERMINE, "
                "ni absence ni refus prouves")
    return agent, nom, etat, detail % (code & 0xFFFFFFFF)


def etat_des_cles(agents=None) -> dict:
    """{agent: {"cle", "etat", "detail"}} -- l'etat CONSULTABLE PAR LE CORPS.

    Mesure du 2026-09-21 : un NR ecrit par EFFET (et non par import) a revele
    que cette information n'existait que dans un `print` de `main()`. Aucune
    autre brique ne pouvait donc s'en servir -- ni un diagnostic, ni une tuile,
    ni un gate. Un etat qu'on ne peut que LIRE dans un terminal n'est pas un
    etat du systeme.

    `_etat_cle` reste la SOURCE UNIQUE : `main` et cette fonction l'appellent
    toutes deux, elles ne peuvent donc pas diverger.

    N'ECRIT RIEN et ne cree aucune cle : la creation est un geste
    ADMINISTRATEUR (NCryptFinalizeKey rend NTE_PERM sous un compte non eleve,
    mesure du 2026-09-20).
    """
    out = {}
    for agent in (agents or AGENTS_ACTIFS):
        try:
            _a, nom, etat, detail = _etat_cle(agent)
        except Exception as exc:          # noqa: BLE001
            # Une sonde qui LEVE ne prouve pas l'absence : INDISPONIBLE, et on
            # dit pourquoi. INDISPONIBLE n'est pas ABSENTE.
            out[agent] = {"cle": None, "etat": "INDISPONIBLE",
                          "detail": "sonde en echec : %s" % exc.__class__.__name__}
            continue
        out[agent] = {"cle": nom, "etat": etat, "detail": detail}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cles TPM par agent (ECDSA P-256)")
    ap.add_argument("--check", action="store_true", help="etat des cles, sans ecrire")
    ap.add_argument("--list", action="store_true", help="agents M2M actifs mesures")
    ap.add_argument("--create", nargs="*", metavar="AGENT", help="cree ces cles (ADMIN)")
    ap.add_argument("--create-actifs", action="store_true", help="cree celles des actifs (ADMIN)")
    ap.add_argument("--acl", metavar="AGENT",
                    help="LIT le descripteur de securite de la cle (aucune ecriture)")
    ap.add_argument("--acl-ajouter", metavar="AGENT",
                    help="PLAN d'ajout d'une ACE (dry-run ; ecrit avec --confirmer)")
    ap.add_argument("--compte", help="compte a autoriser, ex. MACHINE\\Compte")
    ap.add_argument("--droit", help="masque SDDL, ex. GR. FA/GA/KA/WD REFUSES")
    ap.add_argument("--sddl-attendu", help="SDDL capture par --acl (obligatoire)")
    ap.add_argument("--confirmer", action="store_true",
                    help="ECRIT reellement l'ACE (sinon : plan seulement)")
    ap.add_argument("--jkt", metavar="AGENT",
                    help="exporte la cle PUBLIQUE TPM de l'agent et calcule son empreinte "
                         "RFC 7638 (lecture seule)")
    ap.add_argument("--enregistrer", action="store_true",
                    help="avec --jkt : ecrit tpm_jkt au registre d'identite (provenance "
                         "etablie au provisionnement, jamais declaree par le client)")
    args = ap.parse_args(argv)

    if not any((args.check, args.list, args.create is not None,
                args.create_actifs, args.acl, args.acl_ajouter, args.jkt)):
        ap.error("--check, --list, --acl, --acl-ajouter, --jkt, --create ou "
                 "--create-actifs requis")

    if args.jkt:
        # 2026-09-24 (chantier d'authentification, preuve TPM) : le hub compare la cle de
        # la preuve DPoP a l'empreinte ENREGISTREE ici, au provisionnement. La provenance
        # s'etablit par ce registre, jamais par ce que le client affirme de sa cle.
        from nokido_agent.app.forge_dpop import thumbprint
        from nokido_agent.app.forge_m2m_protocol import _resoudre_agent
        from nokido_agent.app.forge_persona_tpm import cle_publique_jwk_agent
        jwk, raison = cle_publique_jwk_agent(args.jkt)
        if not jwk:
            print("REFUS : cle publique TPM de %s non exportable : %s" % (args.jkt, raison))
            return 1
        jkt = thumbprint(jwk)
        print("agent : %s\njkt   : %s" % (args.jkt, jkt))
        if not args.enregistrer:
            print("LECTURE SEULE : relancer avec --enregistrer pour l'ecrire au registre.")
            return 0
        import json as _json
        from datetime import date as _date
        canon, _surface = _resoudre_agent(args.jkt)
        reg_path = _RACINE / "config" / "agent_identities.json"
        brut = reg_path.read_text(encoding="utf-8")
        reg = _json.loads(brut)
        # Ecrire sans reformater : si le fichier ne se relit pas a l'identique, on ne
        # touche a rien -- un diff parasite de milliers de lignes masquerait le vrai.
        if _json.dumps(reg, indent=2, ensure_ascii=False) + "\n" != brut:
            print("REFUS : le registre n'est pas au format canonique (indent=2) ; "
                  "l'ecriture le reformaterait entierement. Rien n'a ete ecrit.")
            return 2
        entree = (reg.get("agents") or {}).get(canon)
        if entree is None:
            print("REFUS : %s absent du registre d'identite" % canon)
            return 2
        entree["tpm_jkt"] = jkt
        entree["tpm_jkt_enregistre_le"] = _date.today().isoformat()
        reg_path.write_text(_json.dumps(reg, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print("ENREGISTRE : agents.%s.tpm_jkt = %s" % (canon, jkt))
        return 0

    from nokido_agent.app.forge_persona_tpm import tpm_available

    admin = _est_admin()
    print("TPM present : %s | admin : %s | magasin MACHINE : %s"
          % (tpm_available(),
             {True: "oui", False: "NON", None: "ILLISIBLE"}[admin],
             os.environ.get("FORGE_TPM_MACHINE") == "1"))

    if args.list:
        print("\nAgents M2M actifs (mesure 2026-09-20 sur agent_messages) :")
        for a in AGENTS_ACTIFS:
            print("   %s" % a)
        return 0

    if args.acl:
        from nokido_agent.app.forge_persona_tpm import (
            descripteur_cle_tpm, nom_cle_agent as _nca)
        try:
            nom = _nca(args.acl)
        except ValueError as exc:
            print("\nREFUS : %s" % str(exc)[:120])
            return 2
        d = descripteur_cle_tpm(nom)
        print("\ncle        : %s" % nom)
        print("etat       : %-12s (rc=0x%08X)" % (d["etat"], d["code"] & 0xFFFFFFFF))
        if d["etat"] != "LISIBLE":
            _mag = "MACHINE" if os.environ.get("FORGE_TPM_MACHINE") == "1" \
                   else "UTILISATEUR"
            print("\nLe descripteur n'a pas pu etre lu. REFUSE n'est pas ABSENTE :")
            print("  REFUSE  la cle existe, ce compte ne peut pas l'ouvrir")
            print("  ABSENTE la cle n'existe pas DANS LE MAGASIN INTERROGE")
            print("\nMagasin interroge ici : %s." % _mag)
            if _mag == "UTILISATEUR":
                print("  /!\\ Une cle creee en MACHINE est ABSENTE d'ici, et ce")
                print("      verdict ne dit RIEN sur son existence reelle.")
                print("      Poser le magasin AVANT de conclure :")
                print("        PowerShell : $env:FORGE_TPM_MACHINE = \"1\"")
                print("        cmd.exe    : set FORGE_TPM_MACHINE=1")
            print("Puis relancer depuis le compte qui PEUT ouvrir la cle.")
            return 1
        print("proprietaire : %s" % (d["proprietaire"] or "?"))
        print("SDDL       : %s" % d["sddl"])
        print("\n-- identites nommees dans l'ACL (SID resolus) --")
        import re as _re
        vus = []
        for sid in _re.findall(r"S-1-[0-9\-]+", d["sddl"] or ""):
            if sid in vus:
                continue
            vus.append(sid)
            print("  %-48s %s" % (sid, _nom_du_sid(sid)))
        for court in sorted(set(_re.findall(r"\(A;[^;]*;[^;]*;[^;]*;[^;]*;([A-Z]{2})\)",
                                            d["sddl"] or ""))):
            print("  %-48s %s" % (court, _SIDS_COURTS.get(court, "alias SDDL")))
        print("\nLECTURE SEULE : aucune ACL n'a ete modifiee, aucune cle touchee.")
        return 0

    if args.acl_ajouter:
        from nokido_agent.app.forge_persona_tpm import (
            nom_cle_agent as _nca2, poser_ace_cle_tpm)
        try:
            nom = _nca2(args.acl_ajouter)
        except ValueError as exc:
            print("\nREFUS : %s" % str(exc)[:120])
            return 2
        r = poser_ace_cle_tpm(nom, args.compte or "", args.droit or "",
                              args.sddl_attendu or "",
                              appliquer=bool(args.confirmer))
        print("\ncle     : %s" % nom)
        print("compte  : %s" % (args.compte or "(non fourni)"))
        print("droit   : %s" % (args.droit or "(non fourni)"))
        print("etat    : %s" % r["etat"])
        if r["refus"]:
            print("\nREFUS : %s" % r["refus"])
            return 1
        print("\nAVANT : %s" % r["avant"])
        print("APRES : %s" % r["apres"])
        if r["applique"]:
            print("\nACE ECRITE. Pour revenir en arriere, reposer le SDDL AVANT")
            print("ci-dessus. Verifier ensuite depuis le compte du hub :")
            print("  --check   (OpenKey + sign + verify)")
            if r.get("aces_perdues"):
                print("\n/!\\ WINDOWS A NORMALISE LA DACL — ce qui a ete DEMANDE")
                print("    n'est pas exactement ce qui a ete OBTENU.")
                print("    ACE presente(s) AVANT et absente(s) APRES :")
                for ace in r["aces_perdues"]:
                    print("      %s" % ace)
                print("    Ce n'est pas un echec de l'ecriture : l'ACE demandee")
                print("    est bien la. Mais la DACL n'est plus celle d'avant,")
                print("    et le SDDL AVANT ci-dessus reste le seul moyen de la")
                print("    restaurer telle quelle.")
            elif r.get("normalise"):
                print("\n/!\\ Drapeaux de DACL modifies par Windows (D:P -> D:PAI)")
                print("    sans perte d'ACE. Constat, pas alerte.")
        else:
            print("\nPLAN SEULEMENT — rien n'a ete ecrit.")
            print("Pour appliquer, relancer la MEME commande avec --confirmer.")
            print("Le SDDL AVANT est re-verifie a ce moment-la : si l'ACL a")
            print("change entre temps, l'ecriture est refusee.")
        return 0

    if args.check:
        print("\n%-16s %-32s %-18s %s" % ("agent", "cle", "etat", "detail"))
        print("-" * 100)
        for a in AGENTS_ACTIFS:
            ag, nom, etat, det = _etat_cle(a)
            print("%-16s %-32s %-18s %s" % (ag, nom or "-", etat, det))
        print("\nABSENTE et REFUSEE appellent des gestes OPPOSES, et le code "
              "NCrypt les distingue :")
        print("  ABSENTE  0x80090016 NTE_BAD_KEYSET / 0x80090011 NTE_NOT_FOUND"
              "  -> provisionner")
        print("  REFUSEE  0x80090010 NTE_PERM"
              "                            -> ouvrir un acces, la cle EXISTE")
        print("Le magasin interroge depend de FORGE_TPM_MACHINE (affiche "
              "ci-dessus) : un ABSENTE ne vaut que POUR CE MAGASIN.")
        return 0

    cibles = list(AGENTS_ACTIFS) if args.create_actifs else list(args.create or ())
    if not cibles:
        print("aucun agent cible"); return 2

    if admin is not True:
        print("\nREFUS : la creation ecrit dans le magasin MACHINE du TPM et exige "
              "une console ADMINISTRATEUR.")
        print("  Mesure : NCryptCreatePersistedKey rend 0x00000000 (OK) puis "
              "NCryptFinalizeKey rend 0x80090010 NTE_PERM.")
        print("  -> relancer cette commande depuis une console admin, HORS agent :")
        print("     set FORGE_TPM_MACHINE=1")
        print("     %s %s --create %s" % (sys.executable, __file__, " ".join(cibles)))
        return 3

    os.environ.setdefault("FORGE_TPM_MACHINE", "1")
    from nokido_agent.app.forge_persona_tpm import ensure_agent_key, nom_cle_agent

    rc = 0
    for a in cibles:
        try:
            nom = nom_cle_agent(a)
        except ValueError as exc:
            print("  REFUSE   %-16s %s" % (a, str(exc)[:80]))
            rc = 1
            continue
        ok = ensure_agent_key(a)
        print("  %-8s %-16s %s" % ("CREEE" if ok else "ECHEC", a, nom))
        if not ok:
            rc = 1
    print("\nVerifier ensuite : --check (depuis le compte qui SIGNERA).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
