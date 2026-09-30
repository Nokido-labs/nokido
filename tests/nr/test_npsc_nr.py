# -*- coding: utf-8 -*-
"""NR — NPSC : le moteur ne peut acquitter que ce qu'il a PROUVE.

Capteur (`forge_npsc_scan`) et juge (`forge_npsc`) sont gardes separement, parce
que ce sont deux facons distinctes de mentir.

Proprietes protegees, chacune payee par une erreur reelle du 2026-09-04 :

1. INVARIANT OWNER — un fichier non versionne, ou classe DATA, ne peut JAMAIS
   constituer a lui seul une preuve de surface protocolaire.
2. Un mot en COMMENTAIRE ne prouve rien. L'AST doit l'eliminer.
   (mesure : un `os.walk` sur 871 Mo laissait un dataset de 277 Mo fabriquer
   des surfaces ; le scan lexical a compte gRPC « actif » sur 9 fichiers alors
   que la preuve structurelle donne 0 import et 14 simples mentions)
3. Le vocabulaire de verdict est FERME.
4. Un instrument non concluant rend NO_VERDICT, jamais un acquittement.
5. Quatre etats de surface donnent quatre verdicts distincts. Un INDICE_SEUL
   qui tomberait en NOT_APPLICABLE ferait disparaitre une norme a instruire.
6. Aucun COMPLIANT sans exigence atomisee.
7. Une sortie VIDE avec rc=0 n'est pas « depot vide », c'est « je n'ai pas vu ».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele); parcours du
#   depot (git grep *.py) (l.311)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_npsc as juge  # noqa: E402
import forge_npsc_scan as capteur  # noqa: E402


# --------------------------------------------------------------------------
# Materiel de test : registre factice, jamais le registre reel, sauf pour le
# test de coherence qui le vise explicitement.
# --------------------------------------------------------------------------

def _registre_factice():
    return {
        "version": "test",
        "autorites": {"ietf": {"nom": "IETF"}},
        "standards": {
            "STD-PROUVE": {"autorite": "ietf", "titre": "declenche par surface prouvee"},
            "STD-ABSENT": {"autorite": "ietf", "titre": "declenche par surface absente"},
            "STD-CITE": {"autorite": "ietf", "titre": "declenche par surface citee sans preuve"},
            "STD-ILLISIBLE": {"autorite": "ietf", "titre": "declenche par surface illisible"},
        },
        "surfaces": {
            "prouvee": {"preuve": {"imports": ["zmq"], "seuil": 1}, "standards": ["STD-PROUVE"], "conditionnels": []},
            "absente": {"preuve": {"imports": ["inexistant_xyz"], "seuil": 1}, "standards": ["STD-ABSENT"], "conditionnels": []},
            "citee": {"preuve": {"imports": ["nulle_part"], "seuil": 1}, "standards": ["STD-CITE"], "conditionnels": []},
            "illisible": {"preuve": {"imports": ["peu_importe"], "seuil": 1}, "standards": ["STD-ILLISIBLE"], "conditionnels": []},
        },
    }


def _surfaces_factices():
    return {
        "prouvee": {"etat": capteur.PROVEN, "score_preuve": 3, "score_indice": 0},
        "absente": {"etat": capteur.ABSENT, "score_preuve": 0, "score_indice": 0},
        "citee": {"etat": capteur.SUSPECT, "score_preuve": 0, "score_indice": 7},
        "illisible": {"etat": capteur.UNREADABLE, "score_preuve": None, "score_indice": None},
    }


def _verdict(lignes, sid):
    return next(l["verdict"] for l in lignes if l["standard"] == sid)


# --------------------------------------------------------------------------
# Le capteur
# --------------------------------------------------------------------------

def test_invariant_data_ne_peut_pas_prouver_une_surface():
    """INVARIANT OWNER : DATA et non-versionne ne portent jamais la preuve."""
    assert capteur.PORTENT_PREUVE == (capteur.CODE, capteur.CONFIG), (
        "la preuve doit rester reservee a CODE et CONFIG")
    assert capteur.DATA not in capteur.PORTENT_PREUVE
    assert capteur.TEST not in capteur.PORTENT_PREUVE, "un test peut viser une surface non livree"
    assert capteur.DOC not in capteur.PORTENT_PREUVE, "une doc decrit, elle n'implemente pas"


def test_classification_range_les_donnees_hors_preuve():
    """Les repertoires de donnees mesures le 2026-09-04 tombent bien en DATA."""
    attendu = {
        "app/forge_rag_engine.py": capteur.CODE,
        "tools/ci_local.py": capteur.CODE,
        "proxy_deno/core/brain.ts": capteur.CODE,
        # Un test ORDINAIRE reste TEST. Ne pas prendre en exemple un fichier du
        # moteur : depuis l'exclusion META, ils sortent META, et l'exemple
        # mesurerait l'exception au lieu de la regle.
        "tests/nr/test_forge_circadian.py": capteur.TEST,
        "docs/ARCHITECTURE.md": capteur.DOC,
        "config/services.toml": capteur.CONFIG,
        "data/quelque_chose.json": capteur.DATA,
        "RAG_plain_bak/longmemeval/longmemeval_s_cleaned.json": capteur.DATA,
        "models/bge_m3_onnx/tokenizer.json": capteur.DATA,
        "shadow_mutation/mut_0001.py": capteur.DATA,
    }
    for chemin, population in attendu.items():
        assert capteur.classer(chemin) == population, (
            "%s classe %s au lieu de %s" % (chemin, capteur.classer(chemin), population))


def test_vendor_ne_prouve_ni_n_indique():
    """ANTI-REGRESSION 2026-09-04 : une dependance TIERCE embarquee ne prouve rien.

    `app/web_hub/static/swagger-ui-bundle.js` etait le SEUL fichier du depot
    citant « webauthn / passkey / fido ». Versionne, extension .js, sous app/ :
    `git ls-files` ne le distingue pas et il sortait en CODE, faisant remonter
    une surface WebAuthn que Nokido n'implemente pas.
    """
    assert capteur.VENDOR not in capteur.PORTENT_PREUVE
    vendored = [
        "app/web_hub/static/swagger-ui-bundle.js",
        "app/web_hub/static/style.min.css",
        "proxy_deno/vendor/lib.ts",
        "app/ui/third_party/chart.bundle.js",
    ]
    for chemin in vendored:
        assert capteur.classer(chemin) == capteur.VENDOR, (
            "%s classe %s au lieu de VENDOR" % (chemin, capteur.classer(chemin)))
    assert capteur.classer("app/forge_rag_engine.py") == capteur.CODE, (
        "le marqueur VENDOR ne doit pas avaler du code legitime")


def test_mot_cle_d_appel_est_une_signature():
    """ANTI-REGRESSION 2026-09-04 : une surface DELEGUEE se prouve par keyword.

    Nokido parle gRPC sans aucun `import grpc` : c'est `qdrant_client` qui le
    fait, active par `prefer_grpc=True`. Sans collecter les mots-cles d'appel,
    la surface sortait INDICE_SEUL a tort et RFC-9113 n'etait jamais considere.
    """
    signaux, err = capteur.signaux_python("client = QdrantClient(host=h, grpc_port=6334, prefer_grpc=True)\n")
    assert signaux is not None, err
    assert "prefer_grpc" in signaux["attributs"], "mot-cle d'appel non collecte"
    assert "grpc_port" in signaux["attributs"]
    capteur.sceller(signaux)
    score, temoins = capteur.correspond({"attributs": ["prefer_grpc", "grpc_port"]}, signaux)
    assert score == 2, "surface deleguee non prouvee : %s" % temoins


def test_le_moteur_ne_se_mesure_pas_lui_meme():
    """ANTI-REGRESSION 2026-09-04 : un instrument qui se mesure mesure son vocabulaire.

    Le registre nomme tous les protocoles qu'il connait, les detecteurs citent
    les litteraux qu'ils cherchent, les tests fabriquent des cas temoins. Sitot
    le registre committe, la surface webauthn — correctement classee ABSENT —
    est repassee SUSPECT : le seul temoin etait la definition de webauthn dans
    le registre lui-meme.

    Troisieme incarnation du motif dans la journee, apres le garde LIKE qui
    criait sur ses propres commentaires et le test dont le motif « introuvable »
    l'a cesse des qu'il a ete committe.
    """
    assert capteur.META not in capteur.PORTENT_PREUVE
    for meta in ("standards/registry.json", "tools/forge_npsc_scan.py",
                 "tools/forge_npsc.py", "tests/nr/test_npsc_nr.py"):
        assert capteur.classer(meta) == capteur.META, (
            "%s classe %s : le moteur va se compter lui-meme" % (meta, capteur.classer(meta)))
    # Et le code ordinaire n'est pas avale par cette exclusion.
    assert capteur.classer("app/forge_rag_engine.py") == capteur.CODE
    assert capteur.classer("tools/forge_npsc_autre_chose.py") == capteur.CODE


def test_ast_elimine_les_commentaires():
    """EFFET : un protocole cite en COMMENTAIRE ne produit aucune signature.

    C'est la propriete qui separe une mesure d'une coincidence lexicale. Sans
    elle, le scan comptait gRPC « actif » sur 9 fichiers qui n'en importaient
    aucun.
    """
    source_commentaire = "# websocket ws:// wss:// et un mot grpc\nx = 1\n"
    signaux, err = capteur.signaux_python(source_commentaire)
    assert signaux is not None, "AST en echec : %s" % err
    capteur.sceller(signaux)
    spec = {"imports": ["websockets"], "chaines": ["ws://", "wss://"], "attributs": ["WebSocket"]}
    score, temoins = capteur.correspond(spec, signaux)
    assert score == 0, "un commentaire a produit %d signature(s) : %s" % (score, temoins)

    source_reelle = "import websockets\nURL = 'ws://127.0.0.1:9000'\n"
    signaux2, _ = capteur.signaux_python(source_reelle)
    capteur.sceller(signaux2)
    score2, temoins2 = capteur.correspond(spec, signaux2)
    assert score2 >= 2, "un import + une URL reels devraient prouver, obtenu %d" % score2
    assert any(t.startswith("import:") for t in temoins2)


def test_docstring_ne_vaut_pas_signature():
    """Une docstring est de la prose, pas une implementation."""
    source = '"""Ce module parle de text/event-stream et de /mcp/sse."""\ny = 2\n'
    signaux, err = capteur.signaux_python(source)
    assert signaux is not None, err
    capteur.sceller(signaux)
    spec = {"chaines": ["text/event-stream", "/mcp/sse"]}
    score, _ = capteur.correspond(spec, signaux)
    assert score == 0, "une docstring a produit %d signature(s)" % score


def test_commentaires_retires_du_repli_lexical():
    """Le repli lexical retire aussi les commentaires, sinon il ment plus que l'AST."""
    signaux = capteur.signaux_lexicaux("// import 'websockets'\n/* ws:// */\nconst a = 1;\n")
    capteur.sceller(signaux)
    score, _ = capteur.correspond({"imports": ["websockets"], "chaines": ["ws://"]}, signaux)
    assert score == 0, "le repli lexical a compte un commentaire"


def test_index_git_vide_est_une_erreur_pas_un_depot_vide():
    """Sortie VIDE avec rc=0 : « je n'ai pas pu voir », jamais « rien a voir »."""
    fichiers, err = capteur.fichiers_versionnes(Path(str(ROOT / "_repertoire_inexistant_npsc")))
    assert fichiers is None, "un chemin non-depot a rendu une liste de fichiers"
    assert err, "echec silencieux : aucune erreur nommee"


def test_index_git_indisponible_rend_tout_illisible():
    """EFFET : sans index, aucune surface n'est declaree absente."""
    surfaces, diag = capteur.inventorier(_registre_factice(), ROOT / "_repertoire_inexistant_npsc")
    assert diag["instrument_ok"] is False
    assert diag["controles"].get("INDEX_GIT") is False
    for nom, mesure in surfaces.items():
        assert mesure["etat"] == capteur.UNREADABLE, (
            "%s declaree %s alors que l'index est indisponible" % (nom, mesure["etat"]))


# --------------------------------------------------------------------------
# Le juge
# --------------------------------------------------------------------------

def test_registre_reel_coherent():
    """Chaque surface declenche des standards declares, rattaches a une autorite connue."""
    reg, err = juge.charger_registre()
    assert reg is not None, "registre illisible : %s" % err
    for surface, spec in reg["surfaces"].items():
        assert spec.get("preuve"), "surface '%s' sans bloc de preuve" % surface
        for sid in (spec.get("standards") or []) + (spec.get("conditionnels") or []):
            assert sid in reg["standards"], (
                "surface '%s' declenche '%s', absent des standards" % (surface, sid))
    for sid, meta in reg["standards"].items():
        assert meta.get("autorite") in reg["autorites"], (
            "standard '%s' rattache a une autorite inconnue : %r" % (sid, meta.get("autorite")))


def test_vocabulaire_de_verdict_ferme():
    reg = _registre_factice()
    diag = {"instrument_ok": True, "controles": {}}
    for ligne in juge.evaluer(reg, _surfaces_factices(), diag):
        assert ligne["verdict"] in juge.VERDICTS, "verdict hors vocabulaire : %r" % ligne["verdict"]


def test_instrument_casse_ne_donne_aucun_acquittement():
    """EFFET : un seul controle en echec et TOUT passe en NO_VERDICT."""
    reg = _registre_factice()
    diag = {"instrument_ok": False, "controles": {"INDEX_COVERAGE": False, "AST_PARSE_RATE": True}}
    lignes = juge.evaluer(reg, _surfaces_factices(), diag)
    assert lignes
    for ligne in lignes:
        assert ligne["verdict"] == "NO_VERDICT", (
            "%s rend %s alors que l'instrument est casse" % (ligne["standard"], ligne["verdict"]))
        assert "INDEX_COVERAGE" in ligne["motif"], "le controle fautif n'est pas nomme"


def test_quatre_etats_quatre_verdicts():
    """PROUVEE / ABSENTE / INDICE_SEUL / ILLISIBLE ne se confondent jamais."""
    reg = _registre_factice()
    diag = {"instrument_ok": True, "controles": {}}
    lignes = juge.evaluer(reg, _surfaces_factices(), diag)
    assert _verdict(lignes, "STD-PROUVE") == "UNVERIFIED"        # applicable, pas de test
    assert _verdict(lignes, "STD-ABSENT") == "NOT_APPLICABLE"    # mesure d'absence
    assert _verdict(lignes, "STD-CITE") == "UNKNOWN"             # citee, pas prouvee
    assert _verdict(lignes, "STD-ILLISIBLE") == "NO_VERDICT"     # pas pu regarder


def test_aucun_compliant_sans_exigence_atomisee():
    """Une regle sans test est UNVERIFIED. Jamais PASS."""
    reg = _registre_factice()
    diag = {"instrument_ok": True, "controles": {}}
    lignes = juge.evaluer(reg, _surfaces_factices(), diag)
    assert not [l for l in lignes if l["verdict"] == "COMPLIANT"], (
        "un COMPLIANT est apparu sans aucune exigence atomisee")


def test_executeur_type_inconnu_ne_donne_pas_un_acquittement():
    """Un executeur qui ne sait pas verifier rend NO_VERDICT, jamais COMPLIANT."""
    res = juge.executer_exigence({"id": "X", "detecteur": {"type": "runtime_probe"}}, ROOT)
    assert res["verdict"] == "NO_VERDICT"
    assert "non branche" in res["motif"]


def test_presence_requise_absente_rend_violation():
    """EFFET : un mecanisme exige par la norme et introuvable = VIOLATION.

    C'est ce qui a fait sortir RFC 9309 en VIOLATION le 2026-09-04 : Nokido
    crawle le web (62 fichiers a requetes sortantes) et `robotparser` /
    `robots.txt` / `can_fetch` n'apparaissent dans AUCUN fichier versionne.
    """
    # Le motif est ASSEMBLE a l'execution : ecrit en clair, il figurerait dans
    # ce fichier, qui est versionne — donc `git grep` le trouverait et le test
    # se contaminerait lui-meme. Mesure du 2026-09-04 : premiere execution apres
    # commit, COMPLIANT au lieu de VIOLATION, temoin = ce fichier de test.
    # Meme famille que le garde LIKE qui criait sur ses propres commentaires.
    introuvable = "zZmotif" + "QuiNexiste" + "PasDansNokido42"
    exigence = {
        "id": "TEST-ABSENT",
        "detecteur": {"type": "presence_requise", "motif": introuvable, "globs": ["*.py"]},
        "si_absent": "VIOLATION",
    }
    res = juge.executer_exigence(exigence, ROOT)
    assert res["verdict"] == "VIOLATION", res
    assert "aucune occurrence" in res["motif"]


def test_presence_requise_satisfaite_rend_compliant_avec_preuve():
    """Symetrique : le mecanisme present rend COMPLIANT et NOMME ses temoins."""
    exigence = {
        "id": "TEST-PRESENT",
        "detecteur": {"type": "presence_requise", "motif": "def evaluer", "globs": ["tools/*.py"]},
        "si_absent": "VIOLATION",
    }
    res = juge.executer_exigence(exigence, ROOT)
    assert res["verdict"] == "COMPLIANT", res
    assert res["preuve"], "un COMPLIANT sans preuve nommee ne vaut rien"


def test_un_seul_no_verdict_contamine_l_agregat():
    """On ne declare pas conforme un standard dont une exigence n'a pas pu etre vue."""
    atomes = [
        {"id": "A", "detecteur": {"type": "presence_requise", "motif": "def evaluer", "globs": ["tools/*.py"]}},
        {"id": "B", "detecteur": {"type": "type_inexistant"}},
    ]
    verdict, motif, details = juge.verdict_des_exigences(atomes, ROOT)
    assert verdict == "NO_VERDICT", "obtenu %s : %s" % (verdict, motif)
    assert len(details) == 2


def test_registre_illisible_ne_rend_pas_un_registre_vide():
    reg, err = juge.charger_registre(ROOT / "standards" / "_inexistant.json")
    assert reg is None
    assert err and "illisible" in err


def test_tout_motif_d_exigence_est_executable_par_git_grep():
    """Un detecteur qui ne s'execute pas ne mesure RIEN, meme s'il se lit bien.

    Mesure 2026-09-04 : le motif `PROTOCOL_TLSv1(?!_2|_3)` etait correct en PCRE
    et invalide pour `git grep -E`, qui est du POSIX ERE. Resultat : `rc=128`,
    RFC-9846 en NO_VERDICT. Le garde de l'auditeur a bien refuse de conclure —
    mais l'exigence, elle, ne mesurait plus rien depuis son ecriture.

    Ce test EXECUTE chaque motif sur un perimetre etroit : seule l'execution
    reelle distingue un motif valide d'un motif plausible.
    """
    reg, err = juge.charger_registre()
    assert reg is not None, err
    motifs = []
    for sid, meta in reg["standards"].items():
        for exigence in meta.get("exigences") or []:
            motif = (exigence.get("detecteur") or {}).get("motif")
            if motif:
                motifs.append((sid, exigence.get("id"), motif))
    assert motifs, "aucune exigence atomisee : ce garde ne mesure rien"
    invalides = []
    for sid, eid, motif in motifs:
        # Perimetre volontairement etroit : on teste la VALIDITE du motif, pas
        # ce qu'il trouve. `standards/` contient peu de fichiers, donc c'est court.
        _fichiers, erreur = juge._git_grep(ROOT, motif, ["standards/*.json"])
        if erreur is not None:
            invalides.append("%s/%s : %s" % (sid, eid, erreur))
    assert not invalides, "motifs non executables par git grep -E :\n  " + "\n  ".join(invalides)


def test_obsolescence_reste_visible():
    """Une norme obsolete n'est pas supprimee du registre : elle est signalee.

    « n'enterre rien » — une norme retiree du registre redeviendrait invisible
    le jour ou un audit demanderait pourquoi elle n'y figure plus.
    """
    reg, _ = juge.charger_registre()
    obsoletes = [s for s, m in reg["standards"].items() if m.get("remplace_par")]
    assert obsoletes, "aucune trace d'obsolescence dans le registre"
    for sid in obsoletes:
        for remplacant in reg["standards"][sid]["remplace_par"]:
            assert remplacant in reg["standards"], (
                "%s renvoie vers %s, absent du registre" % (sid, remplacant))


def test_etat_produit_est_coherent():
    """Si un etat existe, ses verdicts respectent le vocabulaire ferme."""
    etat_p = ROOT / "sandbox" / "npsc_state.json"
    if not etat_p.exists():
        pytest.skip("aucun etat NPSC produit — le garde ne conclut pas d'une absence")
    etat = json.loads(etat_p.read_text(encoding="utf-8"))
    for ligne in etat.get("verdicts") or []:
        assert ligne["verdict"] in juge.VERDICTS, "etat corrompu : %r" % ligne["verdict"]
    for nom, mesure in (etat.get("surfaces") or {}).items():
        assert mesure["etat"] in (capteur.PROVEN, capteur.SUSPECT,
                                  capteur.ABSENT, capteur.UNREADABLE), (
            "etat de surface inconnu pour %s : %r" % (nom, mesure["etat"]))


def test_trois_etapes_sont_decouplees():
    """Le juge doit pouvoir travailler SANS re-scanner le depot.

    Owner, 2026-09-04 : « le moteur fait actuellement trop de travail en meme
    temps ». Sans artefact d'inventaire, chacune des trois etapes rescannerait
    4 217 fichiers — c'est ce couplage qui rendait le moteur laborieux.
    """
    assert hasattr(capteur, "sauver_inventaire") and hasattr(capteur, "charger_inventaire")
    assert hasattr(juge, "cmd_discover") and hasattr(juge, "cmd_applicable")
    # `applicabilite` ne prend QUE des surfaces deja mesurees : aucun chemin,
    # aucune racine, donc aucune lecture de fichier possible.
    reg = _registre_factice()
    appl = juge.applicabilite(reg, _surfaces_factices())
    assert appl["STD-PROUVE"]["applicable"] is True
    assert appl["STD-ABSENT"]["applicable"] is False


def test_inventaire_ancien_reste_lisible():
    """Un artefact ecrit avec l'ancien vocabulaire ne doit pas devenir illisible.

    « n'enterre rien » vaut aussi pour les artefacts : un inventaire d'hier se
    normalise vers le vocabulaire courant, il ne se rejette pas.
    """
    import json as _json
    import tempfile
    ancien = {"surfaces": {"x": {"etat": "PROUVEE"}, "y": {"etat": "INDICE_SEUL"},
                           "z": {"etat": "ABSENTE"}, "w": {"etat": "ILLISIBLE"}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        _json.dump(ancien, fh)
        chemin = fh.name
    surfaces, _diag, err = capteur.charger_inventaire(chemin)
    Path(chemin).unlink(missing_ok=True)
    assert err is None, err
    assert surfaces["x"]["etat"] == capteur.PROVEN
    assert surfaces["y"]["etat"] == capteur.SUSPECT
    assert surfaces["z"]["etat"] == capteur.ABSENT
    assert surfaces["w"]["etat"] == capteur.UNREADABLE
