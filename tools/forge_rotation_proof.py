#!/usr/bin/env python3
"""__FORGE_COLOR__ = 'immunitaire/rotation'

forge_rotation_proof — deroule un cycle de rotation REEL et prouve qu'il SURVIT
AU REDEMARRAGE.

CAP LONG V9, P3. Les NR prouvent la mecanique en memoire ; ce script prouve le
seul maillon qu'aucun test ne peut atteindre : une revocation tient-elle quand
les process qui la portaient sont morts ?

POURQUOI UNE CLE DE PREUVE ET NON UNE CLE DE PRODUCTION
=======================================================
`NOKIDO_ROTATION_PROOF_KEY` n'est reclame par AUCUN module (verifie sur 1862
fichiers de `app/` et `tools/` le 2026-09-21, et re-verifie a chaque execution
par `_garde_nom_libre`). La rotation est donc REELLE — vrai coffre DPAPI, vrai
ledger, vrai redemarrage — sans qu'aucun provider ne puisse tomber. Faire la
preuve sur `GROQ_API_KEY` aurait prouve la meme chose en risquant le routage.

CE QUI N'EST JAMAIS FAIT
========================
Aucune valeur de secret n'est lue, affichee, journalisee ni ecrite dans
l'attestation. Les valeurs sont TIREES ICI par `secrets.token_urlsafe` et ne
quittent jamais le process. Ce qui circule est l'EMPREINTE sha256 tronquee a
12 caracteres — exactement ce que le ledger manipule deja.

SEQUENCE
========
    1. LAFORGE_PYTHON tools/forge_rotation_proof.py avant-restart
    2. --- redemarrage des services, par le lanceur de l'owner ---
    3. LAFORGE_PYTHON tools/forge_rotation_proof.py apres-restart
    4. LAFORGE_PYTHON tools/forge_rotation_proof.py nettoyer

L'etape 3 est la seule qui prouve quelque chose que les NR ne prouvent pas.
L'etape 4 n'est pas optionnelle : une cle de preuve laissee au coffre devient
une cle orpheline, et l'inventaire la comptera comme un secret sans proprietaire.
"""
from __future__ import annotations

# ANCREE EN DEBUT DE LIGNE. La declaration existait deja -- mais collee derriere
# l'ouverture du docstring (`"""__FORGE_COLOR__ = ...`), donc INVISIBLE au census :
# le texte etait present, la declaration non. TEXT_OCCURRENCE != DECLARATION.
__FORGE_COLOR__ = 'immunitaire/rotation'

import argparse
import json
import secrets as _secrets_stdlib
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

NOM = "NOKIDO_ROTATION_PROOF_KEY"
ATTESTATION = RACINE / "sandbox" / "rotation_proof.json"


def _kr():
    from nokido_agent.app import forge_key_rotation as KR
    return KR


def _fs():
    from nokido_agent.app import forge_secrets as FS
    return FS


def _garde_nom_libre() -> None:
    """Refuse de tourner si le nom de preuve a ete adopte par du code reel.

    Un garde qui n'est verifie qu'une fois, le jour ou on l'ecrit, ne garde
    rien : si quelqu'un se met a lire `NOKIDO_ROTATION_PROOF_KEY` en
    production, cette rotation cesserait d'etre inoffensive.
    """
    reclamants = []
    for sous in ("app", "tools"):
        for p in sorted((RACINE / sous).glob("*.py")):
            if p.name == Path(__file__).name:
                continue                      # un instrument ne se lit pas lui-meme
            try:
                if NOM in p.read_text(encoding="utf-8", errors="replace"):
                    reclamants.append("%s/%s" % (sous, p.name))
            except OSError as e:
                print("  [!] %s/%s ILLISIBLE (%s) — la couverture du garde est "
                      "INCOMPLETE, pas vide" % (sous, p.name, type(e).__name__))
    if reclamants:
        raise SystemExit(
            "REFUS : %r est desormais utilise par %s. La rotation de preuve ne "
            "serait plus sans consequence." % (NOM, ", ".join(reclamants)))


def _etat_du_pool() -> dict:
    """Empreintes du pool et verdict de `resolve`. AUCUNE VALEUR."""
    KR = _kr()
    pool = KR._pool(NOM)
    managed, servie = KR.resolve(NOM)
    sante = KR._load_health()
    return {
        "slots": [{"env": n, "empreinte": KR._fp(v),
                   "statut": (sante.get(KR._fp(v)) or {}).get("status", "inconnue"),
                   "utilisable": KR._usable(sante.get(KR._fp(v)))}
                  for n, v in pool],
        "managed": managed,
        "empreinte_servie": KR._fp(servie) if servie else None,
        "ledger": KR.etat_du_ledger(),
    }


def _afficher(titre: str, etat: dict) -> None:
    print("  --- %s ---" % titre)
    print("      ledger        : %s" % etat["ledger"])
    for s in etat["slots"]:
        print("      %-32s %-12s utilisable=%s"
              % (s["env"], s["statut"], s["utilisable"]))
    print("      SERVIE        : %s" % (etat["empreinte_servie"] or "AUCUNE"))


def avant_restart() -> int:
    _garde_nom_libre()
    KR, FS = _kr(), _fs()
    print("PHASE A — installation de K0 et K1, puis revocation de K0")
    print("=" * 70)

    k0 = _secrets_stdlib.token_urlsafe(32)
    k1 = _secrets_stdlib.token_urlsafe(32)
    fp0, fp1 = KR._fp(k0), KR._fp(k1)
    print("  empreintes : K0=%s  K1=%s   (les valeurs ne sortent pas d'ici)"
          % (fp0, fp1))

    # --- K0 ACTIVE. Un echec d'ecriture est DIT, jamais contourne.
    if not FS.set_secret(NOM, k0):
        raise SystemExit(
            "BLOCKED_BY_OPERATOR : l'ecriture au coffre DPAPI a ECHOUE pour le "
            "slot 1. Ce compte n'a pas le droit d'ecrire dans le coffre machine "
            "— relancer ce script depuis une console ADMIN. Rien n'a ete "
            "modifie, aucune etape n'est simulee.")
    FS.invalidate_cache(NOM)
    etat = _etat_du_pool()
    _afficher("K0 ACTIVE", etat)
    if etat["empreinte_servie"] != fp0:
        raise SystemExit("ECHEC : K0 installee n'est pas servie — cycle interrompu.")

    # --- K1 STAGED (slot 2). K0 doit continuer de servir.
    KR.set_key(NOM, k1, slot=2)
    etat = _etat_du_pool()
    _afficher("K1 STAGED", etat)
    if etat["empreinte_servie"] != fp0:
        print("  [!] K1 sert deja alors qu'elle n'est que staged — l'ordre du "
              "pool n'est pas celui attendu. Constat, pas correction.")

    # --- K0 REVOKED : la DECISION, celle qui ne se re-arme pas.
    KR.mark(NOM, k0, "revoked", "rotation de preuve CAP V9 P3")
    etat = _etat_du_pool()
    _afficher("K0 REVOKED / K1 ACTIVE", etat)
    if etat["empreinte_servie"] != fp1:
        raise SystemExit("ECHEC : apres revocation de K0, K1 n'est pas servie.")

    ATTESTATION.parent.mkdir(parents=True, exist_ok=True)
    ATTESTATION.write_text(json.dumps({
        "phase": "avant-restart",
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nom": NOM,
        "empreinte_K0_revoquee": fp0,
        "empreinte_K1_attendue": fp1,
        "etat": etat,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print("  attestation ecrite : %s" % ATTESTATION)
    print()
    print("  ATTENDU APRES REDEMARRAGE : K0 (%s) TOUJOURS refusee, K1 (%s) servie."
          % (fp0, fp1))
    print("  REQUESTED n'est pas ACHIEVED : rien n'est prouve tant que la phase B")
    print("  n'a pas tourne dans des process NEUFS.")
    return 0


def apres_restart() -> int:
    KR = _kr()
    print("PHASE B — la revocation a-t-elle survecu au redemarrage ?")
    print("=" * 70)
    if not ATTESTATION.exists():
        raise SystemExit(
            "REFUS : aucune attestation de phase A. Sans le verdict d'AVANT, "
            "une mesure d'APRES ne prouve rien — on ne sait pas ce qui etait "
            "attendu.")
    att = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    fp0 = att["empreinte_K0_revoquee"]
    fp1 = att["empreinte_K1_attendue"]
    age_min = (time.time() - att["ts"]) / 60.0
    print("  attestation du %s (il y a %.1f min)" % (att["iso"], age_min))

    etat = _etat_du_pool()
    _afficher("ETAT APRES REDEMARRAGE", etat)

    sante = KR._load_health()
    entree_k0 = sante.get(fp0)
    echecs = []
    if entree_k0 is None:
        echecs.append("K0 (%s) a DISPARU du ledger : la revocation ne survit pas "
                      "— une cle revoquee redevient inconnue, donc servable" % fp0)
    elif KR._usable(entree_k0):
        echecs.append("K0 (%s) est de nouveau UTILISABLE (statut %r)"
                      % (fp0, entree_k0.get("status")))
    if etat["empreinte_servie"] != fp1:
        echecs.append("la cle servie est %s, attendue K1 (%s)"
                      % (etat["empreinte_servie"], fp1))

    print()
    if echecs:
        print("  VERDICT : LA REVOCATION N'A PAS SURVECU")
        for x in echecs:
            print("     - %s" % x)
        return 1
    print("  VERDICT : LA REVOCATION A SURVECU AU REDEMARRAGE")
    print("     K0 %s refusee, K1 %s servie, dans des process NEUFS." % (fp0, fp1))
    att["phase"] = "apres-restart"
    att["verdict"] = "SURVECU"
    att["ts_verification"] = time.time()
    ATTESTATION.write_text(json.dumps(att, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    return 0


def nettoyer() -> int:
    """Retire la cle de preuve du coffre ET du ledger.

    Une cle de preuve oubliee devient une cle ORPHELINE : l'inventaire la
    comptera comme un secret sans proprietaire, et quelqu'un perdra du temps a
    chercher qui l'utilise. La reponse est : personne, jamais.
    """
    KR = _kr()
    print("NETTOYAGE de la cle de preuve")
    print("=" * 70)
    retires = []
    try:
        from nokido_agent.app.forge_machine_vault import vault_delete
        for sfx in KR._SUFFIXES:
            nom = NOM + sfx
            try:
                if vault_delete(nom):
                    retires.append(nom)
            except Exception as e:                      # noqa: BLE001
                print("  [!] %s : %s — a retirer A LA MAIN" % (nom, type(e).__name__))
    except ImportError:
        print("  [!] `vault_delete` INTROUVABLE : les entrees du coffre restent.")
        print("      Ce n'est pas un echec silencieux — c'est dit, et il faut")
        print("      les retirer par le chemin du coffre.")

    sante = dict(KR._relire_du_disque())
    avant = len(sante)
    sante = {fp: e for fp, e in sante.items()
             if not (e.get("env") or "").startswith(NOM)}
    KR._save_health(sante)
    print("  coffre  : %d entree(s) retiree(s) %s" % (len(retires), retires or ""))
    print("  ledger  : %d -> %d entree(s)" % (avant, len(sante)))
    if ATTESTATION.exists():
        ATTESTATION.unlink()
        print("  attestation retiree")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("phase", choices=("avant-restart", "apres-restart", "nettoyer",
                                      "etat"))
    a = ap.parse_args()
    if a.phase == "avant-restart":
        return avant_restart()
    if a.phase == "apres-restart":
        return apres_restart()
    if a.phase == "nettoyer":
        return nettoyer()
    _afficher("ETAT COURANT", _etat_du_pool())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
