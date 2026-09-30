# -*- coding: utf-8 -*-
"""NR — une page GENEREE porte son origine, et sa peremption se voit.

CE QUI A ETE MESURE (2026-09-16), sur `docs/wiki/20-Modules-Reference.md` :

    modules REELS sur disque (tools+app)  : 1765
    cites dans la page                    : 1572  (89,1 %)
    ABSENTS                               :  193
    page generee le                       : 2026-08-30  (17 jours)
    modules MODIFIES DEPUIS               : 1204 / 1765  (68 %)

La couverture n'est pas le defaut principal : la PEREMPTION l'est. Les deux
tiers du corps ont bouge depuis que la page a ete ecrite, et RIEN ne le
signale. La page nomme bien son outil (« Page GENEREE par
tools/forge_wiki_modules.py ») mais ne porte ni SHA ni horodatage : personne
ne peut savoir QUEL etat du code elle decrit.

La preuve que ca coute : quelqu'un a constate la derive le 2026-08-30 et a
colle une rustine MANUELLE en tete (« note ajoutee le 2026-08-30 ; le corps
ci-dessous n'a pas ete reecrit ») au lieu de regenerer. Un artefact genere qui
demande une annotation humaine pour dire qu'il a vieilli est un artefact dont
la fraicheur n'est pas mesurable.

C'est la meme famille que le gate `anatomie` (un artefact absent lu comme un
succes) et que `_charger_vitalite` (un registre STALE lu comme une mesure) :
**un artefact sans date n'est pas frais, il est INCONNU.**

CE QUE CE NR VERROUILLE :
  1. la page rendue porte un marqueur machine-lisible (sha + horodatage UTC) ;
  2. l'horodatage est en UTC — piege paye DEUX fois sur ce depot, un « 17:31 »
     local lu comme UTC a failli faire conclure qu'aucun run ne tournait ;
  3. l'etat se classe par liste BLANCHE : n'est FRAIS que ce qui est PROUVE
     frais. Pas de marqueur => INCONNU, jamais FRAIS ;
  4. le sha se lit SANS subprocess — `action=python` du hub refuse `Popen`
     (`WORKSPACE_GUARD`), et un generateur qui ne tourne que dans un shell
     privilegie ne tournerait pas la ou on en a besoin.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_wiki_modules as W  # noqa: E402

MARQUEUR = "<!-- nokido:genere"


def test_le_module_expose_de_quoi_dater_sa_sortie():
    for nom in ("sha_du_depot", "entete_origine", "etat_de_fraicheur"):
        assert hasattr(W, nom), (
            "%s absent : sans lui, la page ne peut pas porter son origine" % nom)


def test_l_entete_porte_le_sha_et_un_horodatage_utc():
    e = W.entete_origine("abc123def456", "2026-09-16T21:30:00Z")
    assert MARQUEUR in e, "marqueur machine-lisible absent : %r" % e[:120]
    assert "abc123def456" in e, "le sha n'apparait pas dans l'entete"
    assert "2026-09-16T21:30:00Z" in e, "l'horodatage n'apparait pas"
    assert e.rstrip().endswith("-->") or "-->" in e, "commentaire HTML non ferme"


def test_l_horodatage_par_defaut_est_en_utc():
    """Piege paye deux fois : un horodatage local lu comme UTC fait conclure
    a tort qu'un run n'a pas eu lieu. Le suffixe Z n'est pas decoratif."""
    e = W.entete_origine("abc123def456")
    m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", e)
    assert m, "aucun horodatage ISO-8601 UTC (suffixe Z) dans %r" % e[:160]


def test_sans_marqueur_l_etat_est_INCONNU_jamais_FRAIS():
    """Liste BLANCHE. Une page d'avant ce cliquet ne doit pas passer pour fraiche."""
    assert W.etat_de_fraicheur("# 20 — Modules Reference\n\nrien\n", "abc123") == "INCONNU"


def test_un_sha_different_rend_PERIME():
    page = W.entete_origine("aaaaaaaaaaaa", "2026-09-16T21:30:00Z") + "\n# titre\n"
    assert W.etat_de_fraicheur(page, "bbbbbbbbbbbb") == "PERIME"


def test_le_meme_sha_rend_FRAIS():
    page = W.entete_origine("aaaaaaaaaaaa", "2026-09-16T21:30:00Z") + "\n# titre\n"
    assert W.etat_de_fraicheur(page, "aaaaaaaaaaaa") == "FRAIS"


def test_un_sha_illisible_rend_INCONNU_et_non_PERIME():
    """`UNKNOWN != NO` : ne pas savoir quel est le HEAD n'est pas la preuve
    d'une derive. Crier PERIME dans ce cas desarmerait le gate."""
    page = W.entete_origine("aaaaaaaaaaaa", "2026-09-16T21:30:00Z") + "\n# titre\n"
    assert W.etat_de_fraicheur(page, None) == "INCONNU"


def test_la_page_rendue_porte_son_origine():
    """Cliquet niveau 3 : c'est `rendre()` qui produit le livrable, pas l'entete seule."""
    fiches = [{"chemin": "tools/x.py", "nom": "x", "doc": "Fait x.",
               "publics": ["f"], "loc": 10}]
    page = W.rendre(fiches, {}, sha="deadbeefcafe", horodatage="2026-09-16T21:30:00Z")
    assert MARQUEUR in page, "rendre() n'inscrit pas l'origine dans la page"
    assert "deadbeefcafe" in page


def test_le_sha_se_lit_sans_subprocess():
    """Le guard du hub REFUSE le lancement d'un sous-processus depuis
    `action=python` : un lecteur de sha qui passerait par un shell ne
    tournerait pas la ou on en a besoin.

    ⚠️ PIEGE PAYE ICI MEME (2026-09-16). La premiere version de ce test
    cherchait les mots interdits dans le TEXTE du module. Il est donc devenu
    ROUGE au moment ou le correctif a ete pose — non pas a cause d'un appel,
    mais parce que la docstring de `sha_du_depot` EXPLIQUE qu'elle n'utilise
    pas `Popen`. Un instrument qui lit son propre vocabulaire condamne le
    commentaire qui le documente ; c'est le 6e exemplaire de ce defaut sur ce
    depot. On juge donc les APPELS (AST), jamais la prose.
    """
    import ast as _ast
    arbre = _ast.parse((ROOT / "tools" / "forge_wiki_modules.py").read_text(
        encoding="utf-8", errors="replace"))
    modules_interdits = {"subprocess"}
    appels_interdits = {"Popen", "run", "check_output", "call", "system", "popen"}
    fautes = []
    for n in _ast.walk(arbre):
        if isinstance(n, _ast.Import):
            fautes += [a.name for a in n.names if a.name.split(".")[0] in modules_interdits]
        elif isinstance(n, _ast.ImportFrom):
            if (n.module or "").split(".")[0] in modules_interdits:
                fautes.append(n.module)
        elif isinstance(n, _ast.Call):
            f = n.func
            # seuls les appels QUALIFIES comptent : `subprocess.run(...)`,
            # `os.system(...)`. Un `run(...)` nu n'est pas un sous-processus.
            if isinstance(f, _ast.Attribute) and f.attr in appels_interdits:
                base = getattr(f.value, "id", None)
                if base in ("subprocess", "os"):
                    fautes.append("%s.%s" % (base, f.attr))
    assert not fautes, (
        "sous-processus utilise pour lire le sha (%s) : le guard du hub le refuse"
        % ", ".join(sorted(set(fautes))))


# ── Le faux positif que le gate DOIT eviter ──────────────────────────────────
# Vu AVANT de poser le gate : juger sur « sha inscrit == HEAD » rend la page
# PERIMEE des le commit suivant, meme s'il ne touche aucun module -- donc une
# seconde apres l'avoir ecrite. Un garde qui crie a faux se fait desarmer.

_FICHES = [
    {"chemin": "tools/a.py", "nom": "a", "doc": "Fait a.", "publics": ["f"], "loc": 10},
    {"chemin": "app/b.py", "nom": "b", "doc": "Fait b.", "publics": [], "loc": 20},
]


def test_un_commit_qui_ne_touche_aucun_module_laisse_la_page_FRAICHE():
    emp = W.empreinte_du_corpus(_FICHES)
    page = W.rendre(_FICHES, {}, sha="1111111111", horodatage="2026-09-16T21:30:00Z")
    # HEAD a avance (autre sha), mais le CONTENU publie est identique.
    assert W.etat_de_fraicheur(page, "2222222222", empreinte_actuelle=emp) == "FRAIS"


def test_une_docstring_modifiee_rend_PERIME():
    page = W.rendre(_FICHES, {}, sha="1111111111", horodatage="2026-09-16T21:30:00Z")
    modifie = [dict(_FICHES[0], doc="Fait a, autrement."), _FICHES[1]]
    assert W.etat_de_fraicheur(
        page, "1111111111",
        empreinte_actuelle=W.empreinte_du_corpus(modifie)) == "PERIME"


def test_l_empreinte_ne_depend_pas_de_l_ordre_de_collecte():
    """`collecter()` parcourt le disque : l'ordre varie d'un systeme a l'autre.
    Une empreinte sensible a l'ordre ferait clignoter le gate sans cause."""
    assert W.empreinte_du_corpus(_FICHES) == W.empreinte_du_corpus(list(reversed(_FICHES)))


def test_une_page_sans_empreinte_rend_INCONNU_et_non_PERIME():
    """Les pages d'avant ce cliquet : on ne SAIT pas, on ne condamne pas."""
    vieille = "<!-- nokido:genere outil=x sha=1111111111 le=2026-09-01T00:00:00Z -->\n"
    assert W.etat_de_fraicheur(vieille, "2222222222", empreinte_actuelle="abc") == "INCONNU"


# ── Cliquet niveau 4 : le CHEMIN REEL, pas seulement la fonction ─────────────
# Lecon payee sur ce depot : `check()` passait ses tests pendant que `--check`
# mourait en NameError, parce qu'aucun test ne traversait le point d'entree.
# Tout nouveau drapeau CLI a un test qui l'emprunte.

def test_le_drapeau_check_existe_et_traverse_le_point_d_entree():
    rc = W.main(["--check"])
    assert rc in (0, 1), "--check doit rendre 0 ou 1, pas %r" % rc


def test_check_est_en_LECTURE_SEULE():
    """Un gate qui ECRIT ne peut pas juger : il rendrait toujours FRAIS."""
    avant = W.OUT.stat().st_mtime if W.OUT.exists() else None
    W.main(["--check"])
    apres = W.OUT.stat().st_mtime if W.OUT.exists() else None
    assert avant == apres, "--check a modifie la page qu'il est cense juger"


def test_la_regeneration_REAPPLIQUE_la_note_des_ports_arretes(tmp_path, monkeypatch):
    """Regenerer effacait une MESURE, et un gate bloquant l'a dit.

    PAYE LE 2026-09-17. `forge_docs_port_annotate` insere apres le H1 une note
    qui nomme les ports ARRETES cites dans la page (`:5557` est mort depuis le
    2026-06-03). J'ai pris cette note pour une rustine bricolee — « la preuve
    que la page a vieilli sans etre regeneree » — et la regeneration l'a
    EFFACEE. Le gate BLOQUANT `capacites (README vs code)` a aussitot rougi :
    « 5557 cite comme vivant ».

    La note n'etait donc pas le symptome, c'etait une mesure que ce generateur
    ne produit pas. Deux producteurs ecrivaient le meme fichier, l'un effacant
    l'autre. Ce test verrouille le chainage.
    """
    cible = tmp_path / "20-Modules-Reference.md"
    monkeypatch.setattr(W, "OUT", cible)
    # La persistance L2 ecrit une SECONDE cible. Sans cette ligne, ce test
    # modifie `tools/forge_card_summaries.json` dans l'arbre juge, et la CI du
    # 2026-09-22 a refuse de capturer pour cette raison exacte — 11 646 tests a
    # zero echec, 21 gates verts, et `process_state=CAPTURE_REFUSED`.
    monkeypatch.setattr(W, "CARDS", tmp_path / "forge_card_summaries.json")
    monkeypatch.setattr(W, "collecter", lambda: [
        # `:5557` avec les deux-points : c'est la forme que l'annotateur
        # reconnait. Ma premiere fixture ecrivait « port 5557 » et le chainage
        # tournait sans rien poser — l'instrument, pas le code.
        {"chemin": "app/brain_worker.py", "nom": "brain_worker",
         "doc": "Worker ZMQ sur :5557.", "publics": [], "loc": 10}])
    monkeypatch.setattr(W, "organes", lambda: {})
    assert W.main([]) == 0
    texte = cible.read_text(encoding="utf-8", errors="replace")
    assert "ports-arretes" in texte, (
        "la note de peremption n'a pas ete reappliquee : la page cite un port "
        "ARRETE comme vivant, et le gate `capacites` rougira")


def test_la_generation_n_ecrit_AUCUN_fichier_du_depot(tmp_path, monkeypatch):
    """Un test qui appelle la generation ne doit rien laisser dans l'arbre.

    Ce NR ne garde pas une ligne, il garde une PROPRIETE : toute cible d'ecriture
    du generateur est substituable au niveau module. Le jour ou une troisieme
    s'ajoute sans point de substitution, ce test le dira — au lieu de laisser la
    CI refuser une capture une demi-heure plus tard, pour un motif qu'il faut
    alors remonter a la main.

        UN INSTRUMENT NE MODIFIE PAS L'ARBRE QU'IL MESURE.
    """
    import pathlib

    avant = {}
    for cible in ("OUT", "CARDS", "RATCHET"):
        chemin = getattr(W, cible, None)
        assert isinstance(chemin, pathlib.Path), (
            f"`{cible}` n'est pas une cible substituable au niveau module : une "
            "ecriture non isolable est une capture refusee en CI"
        )
        if chemin.exists():
            avant[cible] = chemin.stat().st_mtime_ns
        monkeypatch.setattr(W, cible, tmp_path / f"{cible.lower()}.tmp")

    monkeypatch.setattr(W, "collecter", lambda: [
        {"chemin": "app/brain_worker.py", "nom": "brain_worker",
         "doc": "Worker de test.", "publics": [], "loc": 10}])
    monkeypatch.setattr(W, "organes", lambda: {})
    assert W.main([]) == 0

    # Les cibles REELLES n'ont pas bouge : c'est la propriete, pas le rc.
    for cible, mtime in avant.items():
        # On relit le chemin d'origine, pas celui qu'on vient de substituer.
        reel = pathlib.Path(W.ROOT) / pathlib.Path(
            {"OUT": "docs/wiki/20-Modules-Reference.md",
             "CARDS": "tools/forge_card_summaries.json",
             "RATCHET": "tests/nr/docstring_ratchet.json"}[cible])
        if reel.exists():
            assert reel.stat().st_mtime_ns == mtime, (
                f"la generation a modifie {reel.name} dans l'arbre malgre la "
                "substitution de sa cible — une ecriture echappe au point d'injection"
            )
    print(f"[wiki] {len(avant)} cible(s) reelle(s) inchangee(s) apres generation isolee")


def test_sha_du_depot_rend_None_plutot_que_de_deviner():
    """Un depot sans .git doit rendre None (=> INCONNU), pas une chaine inventee."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        assert W.sha_du_depot(Path(d)) is None
