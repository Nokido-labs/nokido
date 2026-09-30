"""NR — le gate REFUSE les appels qui rapatrient un dump non borne dans le contexte.

DEFAUT MESURE le 2026-09-11 : 15 % du quota consomme en 1h30. Poste principal,
les snapshots navigateur rendus INTEGRALEMENT dans la reponse -- `/forge/feed`
~500 lignes de YAML, `/postal` ~200, le hub ~150 -- et **re-factures a chaque
tour suivant**, puisque chaque tour renvoie tout l'historique.

Les outils exposaient pourtant la sortie bornee, et je l'avais lue :

    browser_snapshot          filename -> ecrit dans un fichier AU LIEU de repondre
                              depth · target · max_chars
    browser_network_requests  filename
    browser_console_messages  filename

C'est la TROISIEME fois dans la meme session que je passe a cote d'une option
presente dans la description d'un outil que je venais de lire (`--storage-state`,
`--secrets`, puis `filename`). Une discipline qui a echoue trois fois en trois
heures ne tiendra pas par la seule volonte : elle devient un MUR.

CE GARDE BLOQUE, il ne conseille pas. C'est le premier de ce fichier a le faire,
et c'est delibere : `main()` sort en 0 partout ailleurs (<< nudge, pas mur >>).
Un nudge se lit et s'oublie ; le quota, lui, ne revient pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE / "tools"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hook_capability_gate as G  # noqa: E402


def _bloque(nom, entree):
    """Rend True si le gate refuse l'appel."""
    b, _msg = G.verdict_depense(nom, entree)
    return b


# --------------------------------------------------------------------------
# 1. CE QUI DOIT ETRE REFUSE — un dump entier dans le contexte
# --------------------------------------------------------------------------

def test_snapshot_sans_borne_est_refuse():
    assert _bloque("mcp__playwright__browser_snapshot", {}), (
        "un snapshot non borne rapatrie la page entiere dans le contexte, et ce "
        "contexte est re-facture a CHAQUE tour suivant")


def test_reseau_et_console_sans_fichier_sont_refuses():
    for nom in ("mcp__playwright__browser_network_requests",
                "mcp__playwright__browser_console_messages"):
        assert _bloque(nom, {"static": False}), (
            "%s sans `filename` rend toute la liste dans la reponse" % nom)


def test_le_message_de_refus_donne_la_forme_qui_MARCHE():
    """Un mur qui ne dit pas par ou passer se fait contourner ou desarmer."""
    _b, msg = G.verdict_depense("mcp__playwright__browser_snapshot", {})
    assert "filename" in msg, "le refus doit nommer l'option qui debloque"
    assert any(m in msg for m in ("depth", "target")), (
        "le refus doit citer les autres bornes possibles")


# --------------------------------------------------------------------------
# 2. CE QUI DOIT PASSER — sinon le garde rend l'outil inutilisable
# --------------------------------------------------------------------------

def test_une_borne_suffit_a_debloquer():
    for entree in ({"filename": "snap.md"}, {"depth": 8}, {"target": "e7"},
                   {"max_chars": 4000}):
        assert not _bloque("mcp__playwright__browser_snapshot", entree), (
            "borne %r refusee : le garde rendrait l'outil inutilisable" % entree)


def test_les_autres_outils_navigateur_passent():
    """Naviguer, cliquer, taper ne rapatrient pas de dump : rien a borner."""
    for nom in ("mcp__playwright__browser_navigate",
                "mcp__playwright__browser_click",
                "mcp__playwright__browser_type",
                "mcp__playwright__browser_take_screenshot"):
        assert not _bloque(nom, {}), "%s n'a aucun dump a borner" % nom


def test_les_outils_hors_navigateur_passent():
    for nom in ("mcp__laforge-sovereign-hub__run", "Read", "Edit", "Bash", ""):
        assert not _bloque(nom, {"action": "shell", "code": "echo ok"}), (
            "%s n'est pas concerne par ce garde" % nom)


# --------------------------------------------------------------------------
# 3. LE GARDE DOIT MORDRE SUR LE CAS REELLEMENT PAYE
# --------------------------------------------------------------------------

def test_le_cas_qui_a_coute_le_quota():
    """Exactement l'appel emis sur /forge/feed : aucun argument."""
    bloque, msg = G.verdict_depense("mcp__playwright__browser_snapshot", {})
    assert bloque
    assert "contexte" in msg.lower() or "tour" in msg.lower(), (
        "le message doit expliquer POURQUOI c'est cher : le contexte est "
        "re-facture a chaque tour, un dump se paie N fois")


# --------------------------------------------------------------------------
# 4. LE MEME DEFAUT PAR L'AUTRE PORTE : LE DUMP DE FICHIER
#
# Paye le 2026-09-11, MOINS D'UNE HEURE apres la livraison du garde
# ci-dessus, et par celui qui venait de l'ecrire : un `type` sur le log de la
# CI locale a rapatrie 2 725 696 caracteres (tronques par le hub). Le mur
# navigateur etait en place ; il ne voit pas ce canal.
#
# C'est la lecon du 2026-09-06 appliquee a moi-meme : un garde qu'on franchit
# en changeant d'outil ne garde rien. Le poste n'etait pas << les snapshots >>,
# c'etait << rapatrier une sortie non bornee >>, quelle qu'en soit la source.
#
# Le seuil s'applique a ce que la commande RAMENE. Rediriger vers un fichier,
# filtrer, ou borner ne ramene rien : ces formes passent, et le refus les NOMME.
# --------------------------------------------------------------------------
RUN = "mcp__laforge-sovereign-hub__run"


def _gros(tmp_path, nom="ci.log"):
    f = tmp_path / nom
    f.write_text("x" * (G.DUMP_FICHIER_SEUIL_OCTETS + 5_000), encoding="utf-8")
    return str(f)


def test_dump_le_cas_exact_paye(tmp_path):
    """`type <log de CI>` : la faute commise, mot pour mot."""
    chemin = _gros(tmp_path)
    bloque, msg = G.verdict_depense(RUN, {"action": "shell", "code": 'type "%s"' % chemin})
    assert bloque, (
        "le garde ne mord pas sur le dump de fichier : c'est par cette porte "
        "que le quota est reparti une heure apres avoir ferme l'autre")
    bas = msg.lower()
    assert "findstr" in bas or "tail" in bas, (
        "un mur sans issue se contourne ou se desarme : le refus doit NOMMER "
        "la forme bornee (findstr, Get-Content -Tail)")


def test_dump_les_formes_bornees_passent(tmp_path):
    chemin = _gros(tmp_path)
    formes = [
        'type "%s" | findstr /c:"RESUME"' % chemin,
        "powershell -NoProfile -Command \"Get-Content -LiteralPath '%s' -Tail 40\"" % chemin,
        "powershell -NoProfile -Command \"Get-Content '%s' -TotalCount 50\"" % chemin,
        'findstr /c:"FAILED" "%s"' % chemin,
        'type "%s" > "%s.out"' % (chemin, chemin),   # redirige : ne rapatrie RIEN
    ]
    for code in formes:
        bloque, msg = G.verdict_depense(RUN, {"action": "shell", "code": code})
        assert not bloque, (
            "forme BORNEE refusee -> faux positif. Un garde qui crie a faux se "
            "fait desarmer, et c'est ainsi qu'on perd un garde juste.\n  %s\n  %s"
            % (code, msg))


def test_dump_un_petit_fichier_passe(tmp_path):
    petit = tmp_path / "court.txt"
    petit.write_text("trois lignes\nsuffisent\nici\n", encoding="utf-8")
    assert not _bloque(RUN, {"action": "shell", "code": 'type "%s"' % petit})


def test_dump_un_fichier_ILLISIBLE_ne_bloque_jamais(tmp_path):
    """UNKNOWN n'est pas NO. Un chemin qu'on ne peut pas mesurer n'est pas
    repute gros : sinon le garde refuse du travail legitime sur une absence
    de mesure, ce qui est la faute exactement symetrique."""
    absent = tmp_path / "jamais_ecrit.log"
    assert not _bloque(RUN, {"action": "shell", "code": 'type "%s"' % absent})
    assert not _bloque(RUN, {"action": "shell", "code": "type %BIDON%\\x.log"})


def test_dump_commands_liste_est_couverte_aussi(tmp_path):
    """`commands=[...]` est un second chemin d'entree du meme outil. Un garde
    qui n'en couvre qu'un se franchit en changeant de champ."""
    chemin = _gros(tmp_path)
    assert _bloque(RUN, {"action": "shell", "commands": ["echo ok", 'type "%s"' % chemin]})
