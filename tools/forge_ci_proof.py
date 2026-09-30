"""forge_ci_proof.py — transformer un verdict de CI en PREUVE PORTABLE.

Le SHA identifie le SUJET. Il ne dit pas ce qui a ete juge sur ce sujet, ni selon
quelles regles. Mesure du 2026-09-19 qui a rendu cette distinction necessaire :
`e5ab874eb` (certifie) et `01ad657eb` (publie) different par **une seule entree de
`PURE_TESTS`**. Aucun fichier produit ne change entre les deux, et pourtant les
deux arbres ne declarent pas le meme perimetre de test. Sans empreinte du PLAN,
ces deux certifications seraient indiscernables tout en n'ayant pas juge la meme
chose -- et c'est exactement le raisonnement « meme produit, donc meme
certification » que ce module existe pour rendre impossible.

Trois empreintes DISTINCTES, parce qu'elles repondent a trois questions :

    test_plan_hash       qu'est-ce qui DEVAIT etre execute ?
    ci_contract_hash     selon quelles REGLES l'execution devient-elle un verdict ?
    dependency_lock_hash avec quelles DEPENDANCES ? (chantier B ; None aujourd'hui,
                         et DECLARE non couvert plutot que tu)

Le manifeste est strictement DECLARATIF : des identifiants et des hashes, jamais
une copie de l'environnement. Et `certifie()` est une CONJONCTION CALCULEE, jamais
un drapeau recopie : un booleen qu'on transporte finit toujours par survivre a la
raison qui l'a rendu vrai.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/preuve-de-certification"

import hashlib
import json
from pathlib import Path

# v2 (2026-09-19) : `verdict` portait TROIS semantiques — « la suite n'a pas ete
# jugee », « l'identite du sujet est invalide », « la suite a ete jugee et voici
# son etat ». Deux dimensions les separent, comme `verdict_bloc` l'a fait au
# niveau des blocs. Et `source_sha` devient `target_sha` + `observed_head` : le
# premier est DEMANDE, le second MESURE — un manifeste d'echec portant
# `source_sha` se lirait « le sujet mesure etait S », ce qui serait faux.
SCHEMA = 2

# Ce que le PROCESSUS DE PREUVE a pu faire. Rien a voir avec un resultat de test.
PROCESS_STATES = ("NO_CAPTURE", "CAPTURE_REFUSED", "CAPTURED")

# Ce que la CERTIFICATION vaut. `SUITE_COMPLETE` est impossible tant que le
# processus n'a pas atteint `CAPTURED` — l'incoherence est DECLAREE, jamais
# corrigee en douce : reecrire la donnee ferait disparaitre le defaut.
# `SUITE_PARTIELLE` en fait partie : `--impacte` le produit LEGITIMEMENT, et le
# rabattre sur NON_CERTIFIANT perdrait l'information « on a choisi de ne jouer
# qu'un sous-ensemble » — qui n'est pas « on n'a pas pu mesurer ».
CERTIFICATION_STATES = ("NON_CERTIFIANT", "SUITE_PARTIELLE", "SUITE_INCOMPLETE",
                        "SUITE_COMPLETE")

# Ce que `certifie()` exige par defaut. `dependency_lock_hash` n'y est PAS : il
# arrive avec le chantier B. L'omettre en silence serait le pretendre couvert ;
# il figure donc dans `non_couvert`, et un appelant plus exigeant (la promotion
# dist) le reclame explicitement via `exiger=`.
CHAMPS_REQUIS = ("target_sha", "observed_head", "test_plan_hash",
                 "ci_contract_hash", "environment_fingerprint",
                 "process_state", "certification_state")


def hash_canonique(objet) -> str:
    """sha256 d'une representation CANONIQUE : tri des clefs, separateurs fixes.

    Sans forme canonique, deux plans IDENTIQUES declares dans un ordre different
    rendraient deux empreintes -- et l'empreinte cesserait de mesurer le plan
    pour mesurer la facon de l'ecrire.
    """
    brut = json.dumps(objet, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def hash_plan(pure_tests, blocs_isoles=(), exclusions=()) -> str:
    """Empreinte de ce qui DEVAIT etre execute (le perimetre DECLARE).

    Les exclusions explicites en font partie : un test retire du plan change le
    plan autant qu'un test ajoute, et le taire rendrait un retrait invisible.
    """
    return hash_canonique({
        "pure_tests": sorted({str(t) for t in (pure_tests or ())}),
        "blocs_isoles": sorted({str(c[0] if isinstance(c, (tuple, list)) else c)
                                for c in (blocs_isoles or ())}),
        "exclusions": sorted({str(e) for e in (exclusions or ())}),
    })


def hash_contrat(chemins):
    """(empreinte, illisibles) — les REGLES qui transforment l'execution en verdict.

    Un fichier illisible n'est pas un fichier absent : on ne l'ignore pas, on le
    NOMME et l'appelant decide. Hacher ce qu'on a pu lire en se taisant sur le
    reste produirait une empreinte qui a l'air complete.
    """
    parts, illisibles = {}, []
    for c in sorted({str(x) for x in (chemins or ())}):
        try:
            parts[c] = hashlib.sha256(Path(c).read_bytes()).hexdigest()
        except OSError as e:
            illisibles.append("%s (%s)" % (c, type(e).__name__))
    return hash_canonique(parts), illisibles


# Modules dont la PRESENCE change ce qu'une suite peut exercer. On sonde le
# module, jamais la capacite : mesure du 2026-08-30, `crawl4ai` cherche par
# find_spec dans trois environnements rendait ABSENT alors qu'il est
# CONTENEURISE. L'empreinte dit donc `module_absent`, pas « capacite absente ».
_MODULES_SUBSTRAT = ("torch", "faiss", "onnxruntime", "onnxruntime_directml",
                     "amd_ipu_util")


def empreinte_substrat() -> dict:
    """CPU, parallelisme et modules d'acceleration — en TROIS etats.

    Deux runs du meme sha sur des substrats differents ne sont pas la meme
    experience : un verdict obtenu avec 16 fils et un NPU disponible ne dit pas
    la meme chose qu'un verdict obtenu sans. `empreinte_contexte` couvrait le
    compte, l'interpreteur et des empreintes de FICHIERS — le materiel n'y
    figurait meme pas en angle mort declare (owner, 2026-09-19).

    Ne sonde RIEN qui charge des DLL d'accelerateur : interroger un provider
    ONNX/DirectML a un cout et un effet de bord, et une empreinte ne doit pas
    modifier ce qu'elle mesure.
    """
    import importlib.util as _u
    import os as _os
    import platform as _pl

    sub = {
        "arch": _pl.machine(),
        "processeur": _pl.processor() or "INCONNU",
        "cpu_count": _os.cpu_count(),
        "os": "%s %s" % (_pl.system(), _pl.release()),
        "modules": {},
    }
    try:
        import winreg as _wr
        _k = _wr.OpenKey(_wr.HKEY_LOCAL_MACHINE,
                         r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        sub["modele_cpu"] = _wr.QueryValueEx(_k, "ProcessorNameString")[0].strip()
    except Exception as e:  # noqa: BLE001
        # ILLISIBLE n'est pas ABSENT : sur un compte bride ou hors Windows, on
        # ne sait pas, et le dire vaut mieux que rendre "INCONNU" en silence.
        sub["modele_cpu"] = "ILLISIBLE(%s)" % type(e).__name__
    for m in _MODULES_SUBSTRAT:
        try:
            sub["modules"][m] = "present" if _u.find_spec(m) else "module_absent"
        except Exception as e:  # noqa: BLE001
            sub["modules"][m] = "ILLISIBLE(%s)" % type(e).__name__
    sub["NON_COUVERT"] = [
        "capacites SERVICE ou CONTENEURISEES : l'absence d'un module ne les mesure pas",
        "etat REEL des accelerateurs au runtime (non sonde : charger un provider "
        "aurait un cout et un effet de bord sur ce qu'on mesure)",
        "frequence, thermique et bridage — deux runs du meme CPU peuvent differer",
    ]
    return sub


def manifeste(target_sha, process_state, certification_state, test_plan_hash,
              ci_contract_hash, environment_fingerprint, observed_head=None,
              failure_stage=None, proof_root=None, execution_id=None,
              dependency_lock_hash=None, dependency_match=None,
              contrat_illisible=(), extra=None, substrat=None,
              proof_write_error=None) -> dict:
    """Le manifeste, sans jugement : il DECLARE, `certifie()` decide.

    Il s'ecrit sur TOUS les chemins de sortie, y compris rouges : une preuve qui
    dit pourquoi elle ne certifie pas vaut mieux qu'une absence de preuve, et
    l'absence d'artefact ne doit plus signifier « echec » quand le contrat est
    justement de conserver une preuve NEGATIVE.
    """
    substrat = empreinte_substrat() if substrat is None else substrat
    m = {
        "schema_version": SCHEMA,
        # DEMANDE vs MESURE. Sur un echec avant capture, `observed_head` est None :
        # on ne sait pas quel arbre a tourne, et le taire serait pretendre le savoir.
        "target_sha": str(target_sha or "") or None,
        "observed_head": str(observed_head or "") or None,
        "process_state": process_state,
        "certification_state": certification_state,
        # OBSERVATION, pas synthese : ne transforme jamais un echec d'IDENTITE en
        # echec de TEST (`CAPTURE_REFUSED/HEAD_MISMATCH` n'est pas un test rouge).
        "failure_stage": failure_stage,
        "proof_root": str(proof_root) if proof_root else None,
        "execution_id": execution_id,
        "test_plan_hash": test_plan_hash,
        "ci_contract_hash": ci_contract_hash,
        "dependency_lock_hash": dependency_lock_hash,
        # Le hash dit QUEL environnement est requis ; il ne dit rien sur celui
        # qui a servi. `dependency_match` porte cette seconde affirmation —
        # CONFORME | DIVERGENT | ILLISIBLE — sans laquelle le hash serait une
        # affirmation sur un FICHIER, pas sur l'environnement (owner 2026-09-19).
        "dependency_match": dependency_match,
        # Le substrat REJOINT l'identite d'environnement : sinon deux verdicts
        # obtenus sur des materiels differents porteraient la meme empreinte.
        "environment_fingerprint": hash_canonique(
            {"contexte": environment_fingerprint, "substrat": substrat}),
        # Garde la forme LISIBLE a cote du hash : un hash seul ne se diagnostique
        # pas, et « les empreintes different » n'apprend rien sans le detail.
        "substrate": substrat,
        # Secondaire, JAMAIS substitut du motif initial : si l'ecriture de la
        # preuve echoue, la cause principale reste l'echec de CI.
        "proof_write_error": proof_write_error,
        "contrat_illisible": list(contrat_illisible or ()),
    }
    # Les contradictions sont DITES, pas corrigees : normaliser en silence ferait
    # disparaitre le defaut au lieu de le signaler.
    inc = []
    if process_state not in PROCESS_STATES:
        inc.append("process_state %r hors vocabulaire" % process_state)
    if certification_state not in CERTIFICATION_STATES:
        inc.append("certification_state %r hors vocabulaire" % certification_state)
    if certification_state == "SUITE_COMPLETE" and process_state != "CAPTURED":
        inc.append("SUITE_COMPLETE avec process_state=%s : une suite ne peut pas "
                   "etre complete si la capture n'a pas abouti" % process_state)
    if observed_head and target_sha and not str(observed_head).startswith(str(target_sha)[:12]):
        inc.append("observed_head %s ne commence pas par target_sha %s"
                   % (str(observed_head)[:12], str(target_sha)[:12]))
    m["incoherences"] = inc
    # LE DENOMINATEUR du manifeste lui-meme. Une preuve muette sur ses angles
    # morts se lit comme exhaustive -- meme regle que `empreinte_contexte`.
    m["non_couvert"] = [c for c in ("dependency_lock_hash",) if not m.get(c)]
    if extra:
        m["extra"] = extra
    return m


def certifie(m, exiger=()):
    """(bool, motif) — CONJONCTION CALCULEE a la lecture, jamais un drapeau stocke.

    Un manifeste qui porterait `"certified": true` verrait ce booleen survivre a
    la raison qui l'a rendu vrai. On recalcule donc a chaque lecture, et la
    promotion peut EXIGER davantage (`exiger=("dependency_lock_hash",)`).
    """
    m = m or {}
    if m.get("schema_version") != SCHEMA:
        return False, ("schema %r inconnu (attendu %d) — un manifeste qu'on ne "
                       "sait pas lire n'est pas un manifeste valide"
                       % (m.get("schema_version"), SCHEMA))
    if m.get("incoherences"):
        return False, ("manifeste INCOHERENT : %s" % "; ".join(m["incoherences"][:2]))
    manques = [c for c in tuple(CHAMPS_REQUIS) + tuple(exiger) if not m.get(c)]
    if manques:
        return False, "champ(s) absent(s) : %s" % ", ".join(sorted(set(manques)))
    if m["process_state"] != "CAPTURED":
        return False, ("process_state %s : la preuve n'a pas ete capturee%s — aucun "
                       "verdict de test ne certifie un sujet dont l'identite n'a "
                       "pas ete etablie"
                       % (m["process_state"],
                          " (%s)" % m["failure_stage"] if m.get("failure_stage") else ""))
    if m.get("contrat_illisible"):
        return False, ("contrat partiellement ILLISIBLE (%s) — on ne certifie pas "
                       "selon des regles qu'on n'a pas pu lire"
                       % ", ".join(m["contrat_illisible"][:3]))
    if m.get("dependency_lock_hash") and m.get("dependency_match") != "CONFORME":
        return False, ("lock declare mais environnement %s : un hash de lock sans "
                       "reconciliation n'affirme rien sur ce qui est installe"
                       % (m.get("dependency_match") or "NON RECONCILIE"))
    if m["certification_state"] != "SUITE_COMPLETE":
        return False, ("certification_state %s : seule une suite COMPLETE certifie "
                       "(une execution partielle ou coupee n'a pas tout mesure)"
                       % m["certification_state"])
    return True, ""


def sujet_promouvable(m, exiger=()):
    """(sha, motif) — le sha que H' a le droit de promouvoir, ou None.

    Rend `observed_head`, JAMAIS `target_sha` : le premier est MESURE, le second
    n'est qu'une demande. Sur une preuve certifiante ils sont egaux par
    construction (la capture refuse sinon), mais seul l'un des deux est une
    mesure — meme discipline que `S != D` pour la promotion.
    """
    ok, motif = certifie(m, exiger=exiger)
    if not ok:
        return None, motif
    return m["observed_head"], ""


def ecrire(chemin, m):
    """(ok, motif). Ecrit puis RELIT : conclure sur l'absence d'erreur d'ecriture
    est precisement ce qui laisse passer une preuve tronquee."""
    p = Path(chemin)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(m, indent=2, ensure_ascii=False, sort_keys=True)
                     + "\n", encoding="utf-8")
        relu = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:160])
    if relu != m:
        return False, "relecture differente de ce qui a ete ecrit"
    return True, ""


def lire(chemin):
    """(manifeste|None, motif). ABSENT et ILLISIBLE ne se confondent pas."""
    p = Path(chemin)
    try:
        return json.loads(p.read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        return None, "ABSENT(%s)" % p
    except (OSError, ValueError) as e:
        return None, "ILLISIBLE(%s: %s)" % (type(e).__name__, str(e)[:120])
