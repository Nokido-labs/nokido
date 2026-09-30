# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "infra/deploy : verrou de composition, combinaison exacte des composants"
RELEASE LOCK — la combinaison EXACTE des composants, et si elle a ete testee.

POURQUOI
========
Le super-depot `nokido-workspace` agrege SIX composants (Nokido,
modelcontextprotocol, netcfg-agent, -mcp, -tui, -web). Chacun peut rester vert
individuellement pendant que l'ENSEMBLE devient incoherent : c'est la regression
qu'aucun test de sous-depot ne voit.

MESURE 2026-08-14 : le super-depot pointait Nokido `66906780` alors que Nokido
etait a `54116abd` — QUATRE commits d'ecart, dont la reparation de l'emetteur de
trajectoires. Rien ne signalait que la composition livree n'etait plus celle qui
avait ete testee.

CE QUE LE VERROU DIT, ET CE QU'IL NE DIT PAS
============================================
Il dit : « voici les SHA exacts qui composaient le systeme quand le gate est
passe ». Il ne dit PAS que le code est bon — il dit qu'une combinaison PRECISE a
ete eprouvee, et permet de detecter qu'on livre autre chose.

TROIS ETATS, comme partout ailleurs dans Nokido depuis le 2026-08-14 :
  0 = composition CONFORME au verrou
  1 = DERIVE : un composant a bouge depuis le dernier gate
  2 = INDETERMINE : impossible de lire l'etat (git absent, depot inaccessible).
      Une absence de mesure n'est jamais un succes.

    LAFORGE_PYTHON tools/forge_release_lock.py --emit    # apres un gate vert
    LAFORGE_PYTHON tools/forge_release_lock.py --check   # avant de livrer
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import subprocess
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent          # Nokido/
WORKSPACE = ROOT.parent                                 # super-depot

# OU VIT LE VERROU — mesure 2026-08-14 : le super-depot appartient a
# BUILTIN\Administrateurs et le compte de service (LaForgeTrusted) ne peut PAS y
# ecrire (PermissionError). On ne force aucune ACL pour un fichier de rapport :
# le verrou se replie dans Nokido, qui est versionne et lu par tous.
#
# LIMITE ASSUMEE : le SHA de Nokido inscrit ici est celui d'AVANT le commit du
# verrou lui-meme — un fichier ne peut pas contenir son propre hash. Les CINQ
# autres composants, eux, sont figes exactement. C'est ce decalage d'un commit,
# et lui seul, qui n'est pas verrouille.
_LOCK_WORKSPACE = WORKSPACE / "RELEASE_LOCK.json"
_LOCK_INTERNE = ROOT / "RELEASE_LOCK.json"
# TROISIEME emplacement, et c'est le seul qui marche en pratique — mesure
# 2026-08-14 : AUCUN compte ne peut a la fois LIRE le super-depot et ECRIRE dans
# Nokido. `LaForgeTrusted` ecrit dans Nokido mais ne lit pas le .git parent ;
# `LaForgeSbxOffline` lit le parent mais ne peut pas creer de fichier dans
# Nokido/ ni dans le super-depot (ACL BUILTIN\\Administrateurs). `sandbox/` est
# inscriptible par tous.
# CE QUE CA COUTE, et il faut le savoir : sandbox/ n'est pas versionne. Le verrou
# y remplit sa fonction (detecter une derive de composition entre deux gates)
# mais il ne voyage PAS avec le depot. Pour qu'il accompagne une release, il faut
# le copier dans le super-depot depuis un compte qui y a droit — l'owner.
_LOCK_SANDBOX = ROOT / "sandbox" / "release_lock.json"
LOCK = next((p for p in (_LOCK_WORKSPACE, _LOCK_INTERNE, _LOCK_SANDBOX) if p.exists()),
            _LOCK_WORKSPACE)


def _git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    """(rc, sortie). safe.directory : le depot appartient a un AUTRE compte que
    celui qui execute — piege paye plusieurs fois le 2026-08-14."""
    try:
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(cwd or WORKSPACE), *args],
            capture_output=True, text=True, errors="replace", timeout=60,
        )
        return r.returncode, (r.stdout or "").strip()
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def composition() -> dict:
    """SHA courant de chaque composant. Valeur None = INDETERMINE, jamais 0."""
    rc, head = _git("rev-parse", "HEAD")
    comp: dict = {"workspace": head if rc == 0 else None, "components": {}}
    # `git submodule status` est un SCRIPT SHELL : il exige basename/sed, absents
    # du PATH de plusieurs comptes de service ici (mesure 2026-08-14 :
    # « basename: command not found »). `ls-tree` est une commande INTERNE de git
    # et rend exactement les SHA enregistres — c'est ce que le verrou doit figer.
    # J'avais d'abord conclu a un probleme d'ACL : faux, `rev-parse` passait tres
    # bien. Un outil absent n'est pas un droit refuse.
    rc, out = _git("ls-tree", "HEAD")
    if rc == 0 and out:
        for ligne in out.splitlines():
            morceaux = ligne.split()
            # format : <mode> <type> <sha>\t<chemin> — mode 160000 = submodule
            if len(morceaux) >= 4 and morceaux[0] == "160000" and morceaux[1] == "commit":
                chemin = ligne.split("\t", 1)[1].strip() if "\t" in ligne else morceaux[3]
                sha_courant = None
                rc2, out2 = _git("rev-parse", "HEAD", cwd=WORKSPACE / chemin)
                if rc2 == 0:
                    sha_courant = out2.strip()
                # `ok` exige d'avoir VU le checkout correspondre. Sans lecture
                # possible (submodule non initialise, dossier inaccessible), l'etat
                # est `non_verifie` — surtout pas `ok`. Premiere emission
                # 2026-08-14 : cinq composants sur six avaient sha_checkout=null
                # et s'affichaient `ok`, c'est-a-dire une absence de mesure
                # presentee comme une conformite.
                if sha_courant is None:
                    etat = "non_verifie"
                elif sha_courant == morceaux[2]:
                    etat = "ok"
                else:
                    # on livrerait autre chose que ce qui est enregistre
                    etat = "desynchronise"
                comp["components"][chemin] = {
                    "sha": morceaux[2],
                    "etat": etat,
                    "sha_checkout": sha_courant,
                }
        if comp["components"]:
            return comp

    rc, out = _git("submodule", "status")     # repli historique
    if rc != 0:
        comp["erreur"] = (out or "ls-tree et submodule status muets")[:200]
        return comp
    for ligne in out.splitlines():
        l = ligne.strip()
        if not l:
            continue
        # format : [ -|+|U ]<sha> <chemin> [(describe)]
        drapeau = l[0] if l[0] in "-+U" else " "
        corps = l[1:] if drapeau != " " else l
        morceaux = corps.split()
        if len(morceaux) < 2:
            continue
        comp["components"][morceaux[1]] = {
            "sha": morceaux[0],
            # `-` = non initialise, `+` = checkout different du pointeur enregistre,
            # `U` = conflit de fusion. Aucun n'est un etat de livraison sain.
            "etat": {"-": "non_initialise", "+": "desynchronise",
                     "U": "conflit"}.get(drapeau, "ok"),
        }
    return comp


# ── PROVENANCE SOUVERAINE ─────────────────────────────────────────────────────
# Le verrou dit QUELLE combinaison ; la provenance ajoute QUI l'atteste et rend
# toute retouche DETECTABLE. On signe le contenu CANONIQUE (workspace, SHA des
# composants, date, gate) avec la racine de confiance deja en place :
# forge_persona_tpm.sign() = TPM ECDSA P-256 (asymetrique, « emane de cette
# instance »), repli HMAC-SHA256 si pas de TPM. AUCUNE dependance cloud, aucun
# tiers : c'est l'equivalent souverain d'une attestation SLSA, la ou JFrog/GitHub
# exigent une autorite externe. HONNETETE DU REPLI : le HMAC prouve l'inviolabilite
# et la MEME machine, pas une authorship verifiable par un tiers -- c'est dit dans
# le rapport, jamais survendu.
def _provenance_payload(d: dict) -> bytes:
    """Octets canoniques et STABLES d'un verrou : ce qui est atteste, sans la
    signature elle-meme (un contenu ne peut pas inclure son propre sceau)."""
    comps = {k: (v or {}).get("sha") for k, v in (d.get("components") or {}).items()}
    canon = {"workspace": d.get("workspace"), "components": comps,
             "emis_le": d.get("emis_le"), "gate": d.get("gate")}
    return json.dumps(canon, sort_keys=True, ensure_ascii=False).encode("utf-8")


# CLE MACHINE, jamais USER — un verrou est EMIS sous un compte (owner, ou le
# service qui lance --emit) et VERIFIE sous un autre (le runner CI). Une cle TPM
# USER est per-compte : le runner ne verrait pas la cle du signataire et la
# verification echouerait a tort. La cle MACHINE (FORGE_TPM_MACHINE=1) est unique
# pour la machine, donc verifiable par tous les comptes -- comme le fichier HMAC
# partage. Sa CREATION exige une elevation UNE fois (provisioning owner) ; la
# SIGNATURE, elle, ne demande aucun privilege ensuite.
def _persona_signer():
    """(sign, verify, hmac_key) ou (None, None, None). Force la cle MACHINE le
    temps de l'appel, puis restaure l'environnement."""
    import os as _os
    try:
        import sys as _sys
        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_persona_tpm import sign as _s0, verify as _v0, _hmac_key as _k

        def _with_machine(fn):
            def _wrap(*a, **kw):
                _prev = _os.environ.get("FORGE_TPM_MACHINE")
                _os.environ["FORGE_TPM_MACHINE"] = "1"
                try:
                    return fn(*a, **kw)
                finally:
                    if _prev is None:
                        _os.environ.pop("FORGE_TPM_MACHINE", None)
                    else:
                        _os.environ["FORGE_TPM_MACHINE"] = _prev
            return _wrap

        return _with_machine(_s0), _with_machine(_v0), _k
    except Exception:  # noqa: BLE001 - hors Windows, module absent : provenance degradee, jamais fausse
        return None, None, None


def _sign_provenance(verrou: dict) -> dict:
    payload = _provenance_payload(verrou)
    digest = hashlib.sha256(payload).hexdigest()
    _sign, _verify, _hmac_key = _persona_signer()
    if _sign is None:
        # Pas de signeur : on POSE quand meme l'empreinte (tamper-evidence sans
        # authorship), et on le DIT. Un `scheme:none` ne se lira jamais VALIDE.
        return {"scheme": "none", "digest": digest,
                "raison": "signeur persona indisponible — empreinte sans signature"}
    s = _sign(payload)
    if s:
        return {"scheme": "tpm-ecdsa-p256", "digest": digest, "sig": s.hex()}
    try:
        cle = _hmac_key()
    except RuntimeError:
        # Cle persona illisible pour ce compte (fail-closed depuis 2b-1, 2026-09-28) :
        # meme sortie que sans signeur -- empreinte posee, absence de signature DITE.
        return {"scheme": "none", "digest": digest,
                "raison": "cle persona illisible depuis ce compte — empreinte sans signature"}
    mac = hmac.new(cle, payload, hashlib.sha256).hexdigest()
    return {"scheme": "hmac-sha256", "digest": digest, "sig": mac}


def _verify_provenance(verrou: dict) -> dict:
    """Etat de la signature du verrou : VALIDE / INVALIDE / FALSIFIEE / ABSENTE."""
    prov = verrou.get("provenance") or {}
    if not prov or prov.get("scheme") in (None, "none"):
        return {"etat": "ABSENTE",
                "raison": prov.get("raison", "aucune signature dans le verrou")}
    # L'empreinte d'abord : si le contenu atteste a change depuis la signature,
    # inutile de verifier la signature -- le verrou a ete edite a la main.
    digest = hashlib.sha256(_provenance_payload(verrou)).hexdigest()
    if prov.get("digest") != digest:
        return {"etat": "FALSIFIEE", "scheme": prov.get("scheme"),
                "raison": "le contenu du verrou ne correspond plus a son empreinte "
                          "signee — SHA ou date modifies apres coup"}
    _sign, _verify, _hmac_key = _persona_signer()
    if _sign is None:
        return {"etat": "INDETERMINE", "scheme": prov.get("scheme"),
                "raison": "empreinte intacte mais signeur indisponible pour verifier"}
    payload = _provenance_payload(verrou)
    scheme, sig_hex = prov.get("scheme"), prov.get("sig", "")
    if scheme == "tpm-ecdsa-p256":
        # ACCES != AUTHENTICITE. La cle TPM machine est reservee a son createur et
        # aux admins ; un compte sans ACL (service, runner CI) ne peut ni l'ouvrir
        # ni verifier. verify() rendrait False dans CE cas comme pour une vraie
        # fausse signature -- indistinguable a partir d'un booleen. Or l'empreinte
        # a DEJA prouve que le contenu n'a pas bouge (sinon FALSIFIEE plus haut) :
        # une signature qu'on ne peut pas OUVRIR est INDETERMINEE, jamais INVALIDE.
        # Discriminant : si ce compte ne peut pas signer un probe, il ne peut pas
        # non plus verifier -> defaut d'acces, pas de falsification.
        if _sign(b"_probe_acces_cle_") is None:
            return {"etat": "INDETERMINE", "scheme": scheme,
                    "raison": "cle TPM machine inaccessible depuis ce compte (ACL) ; "
                              "empreinte intacte — verifier depuis le compte signataire "
                              "ou accorder l'ACL au compte du runner"}
        try:
            ok = _verify(payload, bytes.fromhex(sig_hex))
        except Exception:  # noqa: BLE001
            ok = False
        return {"etat": "VALIDE" if ok else "INVALIDE", "scheme": scheme}
    if scheme == "hmac-sha256":
        try:
            cle = _hmac_key()
        except RuntimeError:
            # ACCES != AUTHENTICITE, comme pour la cle TPM plus haut : une cle qu'on ne
            # peut pas lire ne prouve pas un faux (fail-closed depuis 2b-1, 2026-09-28).
            return {"etat": "INDETERMINE", "scheme": scheme,
                    "raison": "cle persona illisible depuis ce compte ; empreinte intacte "
                              "— verifier depuis le compte signataire"}
        expected = hmac.new(cle, payload, hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(expected, sig_hex)
        return {"etat": "VALIDE" if ok else "INVALIDE", "scheme": scheme,
                "note": "HMAC : inviolabilite + meme machine, pas de verif par un tiers"}
    return {"etat": "INDETERMINE", "raison": f"schema de signature inconnu : {scheme}"}


def gate_coherence() -> tuple[int, dict]:
    """Coherence PURE de la composition, INDEPENDANTE du verrou fige : chaque
    gitlink du super-depot EGALE-t-il le HEAD reel du sous-depot ?

    C'est le Composition Integrity Gate : il attrape immediatement le cas
    recurrent -- Nokido avance, le super-depot reste en arriere et pointe un
    commit perime. Comme `Nokido/` est A LA FOIS le sous-module et le depot
    Nokido, un commit dans Nokido non suivi d'un bump du super-depot rend le
    gitlink (ancien) != HEAD (nouveau) => DRIFTED, visible AVANT meme que le code
    ne soit mauvais. 0 COMPOSED / 1 DRIFTED / 2 INDETERMINE.
    """
    c = composition()
    if c.get("workspace") is None or "erreur" in c or not (c.get("components") or {}):
        return 2, {"etat": "INDETERMINE",
                   "raison": (c.get("erreur")
                              or "composition non lisible — compte sans acces au "
                                 ".git du super-depot ? Lancer depuis l'owner.")}
    mauvais = [{"composant": k, "etat": v.get("etat"),
                "gitlink": (v.get("sha") or "?")[:12],
                "head": (v.get("sha_checkout") or "?")[:12]}
               for k, v in c["components"].items() if v.get("etat") != "ok"]
    if mauvais:
        return 1, {"etat": "DRIFTED", "workspace": (c["workspace"] or "?")[:12],
                   "incoherents": mauvais}
    return 0, {"etat": "COMPOSED", "workspace": (c["workspace"] or "?")[:12],
               "composants": len(c["components"])}


class CompositionIllisible(RuntimeError):
    """La composition n'a pas pu etre lue : on n'emet PAS de verrou."""


def emettre(gate: str = "UNKNOWN", note: str = "") -> dict:
    c = composition()
    # UN VERROU VIDE EST PIRE QU'AUCUN VERROU — mesure 2026-08-14 : la premiere
    # emission a produit `workspace: null, components: {}` et annonce
    # « verrou emis ». Il pretendait figer une composition qu'il n'avait pas pu
    # lire (le compte de service ne peut pas lire le .git du super-depot, dont
    # les ACL appartiennent a BUILTIN\\Administrateurs). Un fichier de
    # verrouillage sans composant se lirait plus tard comme « rien n'a bouge ».
    if not c.get("workspace") or not (c.get("components") or {}):
        raise CompositionIllisible(
            "composition non lisible (workspace={}, {} composant(s)) : "
            "aucun verrou emis. Relancer depuis un compte qui peut lire le .git "
            "du super-depot.".format(c.get("workspace"), len(c.get("components") or {}))
        )
    verrou = {
        "schema": 1,
        "emis_le": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gate": gate,          # PASS / FAIL / UNKNOWN — jamais un booleen
        "note": note,
        **c,
    }
    # Provenance : signer le contenu canonique AVANT de serialiser. La signature
    # scelle (workspace, SHA composants, date, gate) -- toute retouche ulterieure
    # du fichier casse la verification.
    verrou["provenance"] = _sign_provenance(verrou)
    contenu = json.dumps(verrou, ensure_ascii=False, indent=2) + "\n"
    # Repli en cascade, TOUJOURS annonce : savoir OU vit le verrou fait partie
    # du verrou. Un verrou qu'on ne retrouve pas ne verrouille rien.
    echecs = []
    cible = None
    for candidat in (LOCK, _LOCK_INTERNE, _LOCK_SANDBOX):
        if cible is not None:
            break
        try:
            candidat.parent.mkdir(parents=True, exist_ok=True)
            candidat.write_text(contenu, encoding="utf-8")
            cible = candidat
        except OSError as e:
            echecs.append(f"{candidat} ({type(e).__name__})")
    if cible is None:
        raise CompositionIllisible(
            "verrou non ecrit — aucun emplacement inscriptible : " + " ; ".join(echecs)
        )
    if echecs:
        print(f"[verrou] emplacements refuses : {' ; '.join(echecs)} -> ecrit dans "
              f"{cible}", flush=True)
    verrou["_fichier"] = str(cible)
    return verrou


def verifier() -> tuple[int, dict]:
    """(code, rapport). 0 conforme / 1 derive / 2 indetermine."""
    if not LOCK.exists():
        return 2, {"etat": "INDETERMINE", "raison": "aucun RELEASE_LOCK.json — "
                   "la composition livree n'a jamais ete verrouillee"}
    try:
        verrou = json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return 2, {"etat": "INDETERMINE", "raison": f"verrou illisible ({e})"}

    # Un verrou SANS COMPOSANT se lirait comme « rien n'a bouge » : aucune
    # attente, donc aucune derive possible. C'est le faux-vert parfait, et il a
    # ete produit pour de vrai le 2026-08-14. On le rejette a la LECTURE aussi,
    # pas seulement a l'ecriture : un fichier deja pose ne doit pas pouvoir
    # rassurer.
    if not (verrou.get("components") or {}) or not verrou.get("workspace"):
        return 2, {"etat": "INDETERMINE",
                   "raison": "verrou VIDE (aucun composant fige) — il ne prouve "
                             "rien ; le re-emettre depuis un compte qui lit le "
                             ".git du super-depot"}

    actuel = composition()
    if actuel.get("workspace") is None or "erreur" in actuel:
        return 2, {"etat": "INDETERMINE",
                   "raison": f"composition non lisible : {actuel.get('erreur', 'git muet')}"}

    derives, malsains = [], []
    attendus = (verrou.get("components") or {})
    for nom, cur in (actuel.get("components") or {}).items():
        att = attendus.get(nom)
        if att is None:
            derives.append({"composant": nom, "avant": "(absent du verrou)",
                            "apres": cur["sha"][:12]})
        elif att.get("sha") != cur["sha"]:
            derives.append({"composant": nom, "avant": att.get("sha", "?")[:12],
                            "apres": cur["sha"][:12]})
        if cur.get("etat") != "ok":
            # `non_verifie` compte comme malsain : on ne livre pas sur une
            # composition dont on n'a pas pu lire une partie.
            malsains.append({"composant": nom, "etat": cur["etat"]})
    manquants = [n for n in attendus if n not in (actuel.get("components") or {})]

    rapport = {
        "verrou_emis_le": verrou.get("emis_le"),
        "gate_du_verrou": verrou.get("gate", "UNKNOWN"),
        "workspace_verrou": (verrou.get("workspace") or "?")[:12],
        "workspace_actuel": (actuel.get("workspace") or "?")[:12],
        "derives": derives, "malsains": malsains, "manquants": manquants,
        # Provenance du verrou LU : atteste que son contenu est authentique et
        # n'a pas ete edite a la main depuis l'emission. Distinct de la derive,
        # qui compare au REEL courant.
        "provenance": _verify_provenance(verrou),
    }
    # Un verrou pose sur un gate NON concluant ne prouve rien : on le dit.
    if str(verrou.get("gate", "")).upper() not in ("PASS",):
        rapport["avertissement"] = (
            f"le verrou a ete emis avec gate={verrou.get('gate')} : il fige une "
            f"composition, il n'atteste PAS qu'elle a ete eprouvee")
    # DERIVE et INDETERMINE ne se confondent pas -- le module annonce trois etats
    # depuis sa docstring, mais `malsains` (composant `non_verifie`) tombait dans
    # le meme sac que `derives`. Mesure 2026-08-29 : le verrou criait DERIVE avec
    # `workspace_verrou == workspace_actuel` et AUCUN sha change, uniquement cinq
    # submodules illisibles sous le compte courant. On envoie alors chercher une
    # derive qui n'existe pas, au lieu d'un probleme d'ACCES.
    if derives or manquants:
        return 1, {"etat": "DERIVE", **rapport}
    if malsains:
        return 2, {"etat": "INDETERMINE",
                   "raison": "%d composant(s) NON VERIFIE(S) : %s -- rien n'a bouge, "
                             "mais une partie de la composition n'a pas pu etre lue"
                             % (len(malsains), [m["composant"] for m in malsains][:6]),
                   **rapport}
    return 0, {"etat": "CONFORME", **rapport}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit", action="store_true", help="fige la composition courante")
    ap.add_argument("--gate", default="UNKNOWN", choices=["PASS", "FAIL", "UNKNOWN"],
                    help="verdict du gate au moment de l'emission")
    ap.add_argument("--note", default="")
    ap.add_argument("--check", action="store_true", help="0 conforme / 1 derive / 2 indetermine")
    ap.add_argument("--coherence", action="store_true",
                    help="Composition Integrity Gate : 0 COMPOSED / 1 DRIFTED / 2 INDETERMINE "
                         "(gitlink == HEAD de chaque sous-depot, sans verrou fige)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.coherence:
        code, rap = gate_coherence()
        if a.json:
            print(json.dumps(rap, ensure_ascii=False, indent=2))
            return code
        print(f"[composition] {rap['etat']}  workspace={rap.get('workspace', '?')}")
        for m in rap.get("incoherents", []):
            print(f"   DRIFT  {m['composant']:<20} gitlink {m['gitlink']} != HEAD "
                  f"{m['head']}  ({m['etat']})")
        if rap.get("raison"):
            print(f"   {rap['raison']}")
        if code == 1:
            print("   -> bumper le super-depot sur le HEAD du sous-depot, ou "
                  "checkout le sous-depot sur le gitlink attendu.")
        return code

    if a.emit:
        try:
            v = emettre(a.gate, a.note)
        except CompositionIllisible as e:
            print(f"[verrou] INDETERMINE — {e}")
            return 2      # jamais 0 : ne pas laisser croire a un verrou pose
        print(json.dumps(v, ensure_ascii=False, indent=2) if a.json
              else f"[verrou] {v.get('_fichier', LOCK.name)} emis — gate={v['gate']} — "
                   f"{len(v.get('components') or {})} composant(s)")
        return 0

    code, rapport = verifier()
    if a.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return code
    etat = rapport.get("etat")
    print(f"[verrou] {etat}")
    for cle in ("verrou_emis_le", "gate_du_verrou", "workspace_verrou", "workspace_actuel"):
        if rapport.get(cle):
            print(f"   {cle:<18} {rapport[cle]}")
    _prov = rapport.get("provenance") or {}
    if _prov:
        _sc = f" ({_prov.get('scheme')})" if _prov.get("scheme") else ""
        print(f"   {'provenance':<18} {_prov.get('etat')}{_sc}")
        if _prov.get("raison"):
            print(f"                      {_prov['raison']}")
    for d in rapport.get("derives", []):
        print(f"   DERIVE  {d['composant']:<26} {d['avant']} -> {d['apres']}")
    for m in rapport.get("malsains", []):
        print(f"   ETAT    {m['composant']:<26} {m['etat']}")
    for n in rapport.get("manquants", []):
        print(f"   ABSENT  {n}")
    if rapport.get("avertissement"):
        print(f"   ⚠ {rapport['avertissement']}")
    if rapport.get("raison"):
        print(f"   {rapport['raison']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
