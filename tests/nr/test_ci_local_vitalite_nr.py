"""NR — registre de vitalite des gardes (tools/ci_local.py).

Le manque revele le 2026-08-18 : `_INCONCLUS` ne voit qu'UN run, donc rien ne
mesure DEPUIS QUAND un gate a rendu un verdict reel. Un garde qui cesse d'etre
lance ne produit plus de ligne du tout — il ne passe pas au rouge, il DISPARAIT,
et son domaine se lit comme vert. Deux occurrences payees : semgrep affichant
`scanned_files=0` sous une coche verte pendant des semaines, et le cliquet de
mutation reste INDETERMINE muet.

Tests d'EFFET, jamais d'import : ce qui compte est la DISCRIMINATION — un
UNKNOWN rajeunit-il le garde (il ne doit pas), un vieux verdict critique
bloque-t-il, un run partiel s'abstient-il de bloquer.

Hermetique : les DEUX sources (`VITALITE` et le repli `VITALITE_ATTENTE`) sont
monkeypatchees vers tmp_path (une lecture du working
tree casserait en CI propre — mesure du 2026-08-15).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ci_local as C  # noqa: E402


@pytest.fixture()
def registre(tmp_path, monkeypatch):
    """Isole le cliquet ET la liste globale d'inconclus de ce processus pytest."""
    cible = tmp_path / "vitalite_gardes.json"
    monkeypatch.setattr(C, "VITALITE", cible)
    # ⚠️ PAYE 2026-09-16 : `_charger_vitalite` lit DEUX sources
    # (`VITALITE` versionnee ET `VITALITE_ATTENTE`, le depot des runs sandbox)
    # et garde la plus RECENTE. Ne patcher que la premiere laissait le repli de
    # PRODUCTION etre lu des que `cible` etait absent : le test mesurait alors
    # l'anergie REELLE du depot (archi-lint, 17 j) en croyant lire un registre
    # vide, et rendait LU/FRESH/FULL sans qu'aucun fichier de test existe.
    # Un test qui lit un artefact de production n'est pas un test.
    monkeypatch.setattr(C, "VITALITE_ATTENTE", cible)
    # Ces globaux sont ecrits PAR `_charger_vitalite` et survivent d'un test a
    # l'autre : sans remise a zero, un test herite du verdict du precedent.
    monkeypatch.setattr(C, "_VITALITE_ETAT", "ABSENT")
    monkeypatch.setattr(C, "_VITALITE_SOURCE", None)
    monkeypatch.setattr(C, "_VITALITE_FRAICHEUR", "INCONNUE")
    monkeypatch.setattr(C, "_VITALITE_PERIMETRE", "UNKNOWN")
    monkeypatch.setattr(C, "_INCONCLUS", [])
    monkeypatch.delenv("CI", raising=False)
    return cible


# ── cle stable : le meme garde ne doit pas se dedoubler entre deux etats ─────

def test_la_cle_survit_aux_suffixes_d_etat():
    # Le cliquet de mutation s'appelle "... [INDETERMINE]" dans results et sans
    # suffixe dans _INCONCLUS : deux cles = deux gardes = anergie invisible.
    assert C._cle_garde("mutation-ratchet [INDETERMINE]") == C._cle_garde("mutation-ratchet")
    assert C._cle_garde("flake8 critique (E9,F63,F7)") == "flake8 critique"


# ── un UNKNOWN ne rajeunit PAS le garde ──────────────────────────────────────

def test_un_verdict_reel_horodate_et_remet_le_compteur_a_zero(registre):
    r = C._maj_vitalite([("gitleaks", True)], {"gitleaks": {"unknown_consecutifs": 4}}, "2026-08-18")
    assert r["gitleaks"]["dernier_reel"] == "2026-08-18"
    assert r["gitleaks"]["etat"] == "PASS"
    assert r["gitleaks"]["unknown_consecutifs"] == 0


def test_un_echec_est_un_verdict_reel(registre):
    # FAIL est une MESURE : le garde est vivant, meme s'il mord.
    r = C._maj_vitalite([("gitleaks", False)], {}, "2026-08-18")
    assert r["gitleaks"] == {"dernier_reel": "2026-08-18", "etat": "FAIL", "unknown_consecutifs": 0}


def test_un_unknown_ne_touche_pas_au_dernier_verdict_reel(registre, monkeypatch):
    monkeypatch.setattr(C, "_INCONCLUS", [("gitleaks", True, None)])
    avant = {"gitleaks": {"dernier_reel": "2026-08-01", "etat": "PASS", "unknown_consecutifs": 0}}
    r = C._maj_vitalite([("gitleaks", True)], avant, "2026-08-18")
    # `_run` rend True pour un UNKNOWN (« pas un echec du CODE ») : c'est
    # exactement ce True-la qui ne doit pas passer pour une mesure.
    assert r["gitleaks"]["dernier_reel"] == "2026-08-01"
    assert r["gitleaks"]["dernier_unknown"] == "2026-08-18"
    assert r["gitleaks"]["unknown_consecutifs"] == 1


def test_le_compteur_d_unknown_compte_des_JOURS_pas_des_runs(registre, monkeypatch):
    monkeypatch.setattr(C, "_INCONCLUS", [("gitleaks", True, None)])
    r = {}
    for _ in range(3):   # trois runs le meme jour
        r = C._maj_vitalite([("gitleaks", True)], r, "2026-08-18")
    assert r["gitleaks"]["unknown_consecutifs"] == 1
    r = C._maj_vitalite([("gitleaks", True)], r, "2026-08-19")
    assert r["gitleaks"]["unknown_consecutifs"] == 2


# ── detection de l'anergie ───────────────────────────────────────────────────

def test_anergie_seuil_et_jamais_mesure(registre):
    reg = {
        "gitleaks": {"dernier_reel": "2026-07-01"},          # 48 j : anergique, critique
        "flake8 critique": {"dernier_reel": "2026-08-16"},   # 2 j  : vivant
        "semgrep": {},                                        # jamais : -1
    }
    trouves = {cle: (ecart, crit) for cle, ecart, crit in C._anergiques(reg, "2026-08-18")}
    assert trouves["gitleaks"] == (48, True)
    assert trouves["semgrep"][0] == -1
    assert "flake8 critique" not in trouves


def test_le_seuil_est_strict(registre):
    veille = {"gitleaks": {"dernier_reel": "2026-08-04"}}      # exactement 14 j
    assert C._anergiques(veille, "2026-08-18") == []
    assert C._anergiques({"gitleaks": {"dernier_reel": "2026-08-03"}}, "2026-08-18")


# ── verdict de _summary ──────────────────────────────────────────────────────

def _semer(cible: Path, cle: str, jour: str) -> None:
    """Registre COMPLET : `observe_le` et `perimetre` sont OBLIGATOIRES.

    MESURE 2026-09-16 : ces deux champs ont ete ajoutes au format du registre
    APRES l'ecriture de ces tests, et ce semeur n'avait pas suivi. Sans eux,
    `_charger_vitalite` rend FRAICHEUR=INCONNUE et PERIMETRE=UNKNOWN, donc
    `_vit_sur` est faux et le blocage sur anergie ne se declenche JAMAIS : deux
    tests mesuraient l'absence de ces champs au lieu du comportement qu'ils
    annoncent. Un semeur qui ne suit pas le format teste autre chose que ce
    qu'il croit.
    """
    # ⚠️ `observe_le` est la fraicheur du REGISTRE, pas celle du garde : c'est
    # TOUJOURS aujourd'hui. Mon premier correctif y mettait `jour`, or `jour`
    # est la date du dernier verdict du garde (2026-01-01 pour simuler une
    # anergie) -- le registre ressortait STALE de 258 jours, `_vit_sur` restait
    # faux, et le test echouait toujours pour une raison NOUVELLE. Deux dates
    # differentes dans le meme objet, c'est deux sens : ne pas les confondre.
    cible.write_text(json.dumps({
        "observe_le": str(date.today()),
        "perimetre": "FULL",
        "gardes": {cle: {"dernier_reel": jour, "etat": "PASS"}},
    }), encoding="utf-8")


def test_un_garde_critique_anergique_bloque_la_livraison(registre):
    _semer(registre, "gitleaks", "2026-01-01")
    # Aucun gate en echec dans ce run : sans le registre, ce resume serait VERT.
    assert C._summary([("flake8 critique (E9,F63,F7)", True)]) == 1


def test_un_run_partiel_nomme_l_anergie_sans_bloquer(registre, capsys):
    _semer(registre, "gitleaks", "2026-01-01")
    assert C._summary([("flake8 critique (E9,F63,F7)", True)], partiel=True) == 0
    assert "ANERGIQUE" in capsys.readouterr().out   # nomme quand meme


def test_un_garde_non_critique_ne_bloque_pas(registre):
    _semer(registre, "docker build", "2026-01-01")
    assert C._summary([("flake8 critique (E9,F63,F7)", True)]) == 0


# ── ecriture du cliquet ──────────────────────────────────────────────────────

def test_le_coffre_se_retrouve_depuis_un_worktree_DETACHE(tmp_path, monkeypatch):
    """AUTH_FAILURE du gate UI : un defaut de CHEMIN, pas d'interface.

    MESURE 2026-09-17. En `--reference`, `ROOT` est un worktree detache et
    `data/` est gitignore : `data/machine_vault.dat` n'y est PAS. La cascade de
    `forge_secrets` descend jusqu'a `os.environ`, ne trouve rien, et la
    campagne rend AUTH_FAILURE — « on a vu le formulaire de login, pas les
    pages ». Ca se lit comme une interface cassee alors que c'est le coffre
    qu'on cherchait au mauvais endroit. Meme defaut que le 2026-09-16 cote
    runner GitHub, ou la reponse fut de poser `LAFORGE_VAULT_PATH` ; la CI
    LOCALE, elle, ne le posait toujours pas.
    """
    depot = tmp_path / "depot"
    (depot / "data").mkdir(parents=True)
    coffre = depot / "data" / "machine_vault.dat"
    coffre.write_bytes(b"x" * 16)
    gitdir = depot / ".git" / "worktrees" / "wt1"
    gitdir.mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: %s\n" % gitdir, encoding="utf-8")

    monkeypatch.setattr(C, "ROOT", wt)
    assert C._coffre_de_l_installation() == coffre


def test_sans_coffre_trouvable_on_rend_None_plutot_que_de_deviner(tmp_path, monkeypatch):
    """Un chemin invente couterait une enquete : un coffre ABSENT et un coffre
    VIDE se lisent tous deux « secret absent »."""
    monkeypatch.setattr(C, "ROOT", tmp_path)
    assert C._coffre_de_l_installation() is None


def test_tout_subprocess_mode_texte_declare_errors(monkeypatch):
    """`text=True` sans `errors=` fait lever le LECTEUR, pas la commande.

    MESURE : 3 sites dans `ci_local.py` (rev-parse, git add, git commit). Un
    octet non decodable dans la sortie fait echouer `_readerthread` a
    l'interieur de `subprocess` — l'exception ne vient donc pas de git et
    remonte la ou personne ne l'attend. Anti-regression de l'incident 47 Go,
    signale par le gate `firehose` a chaque commit.

    On juge les APPELS (AST), jamais le texte : un test qui chercherait la
    chaine « errors » condamnerait le commentaire qui l'explique.
    """
    import ast as _ast
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8",
                                                     errors="replace")
    fautifs = []
    for n in _ast.walk(_ast.parse(src)):
        if not isinstance(n, _ast.Call):
            continue
        f = n.func
        if not (isinstance(f, _ast.Attribute) and f.attr in ("run", "Popen")
                and getattr(f.value, "id", None) == "subprocess"):
            continue
        kw = {k.arg for k in n.keywords if k.arg}
        mode_texte = any(k.arg in ("text", "universal_newlines")
                         and getattr(k.value, "value", None) is True
                         for k in n.keywords if k.arg)
        if mode_texte and "errors" not in kw:
            fautifs.append(n.lineno)
    assert not fautifs, (
        "subprocess en mode texte SANS errors= aux lignes %s : une sortie non "
        "decodable y fait crasher le lecteur" % fautifs)


def test_l_anergie_nomme_le_suppleant_CONSTATE_a_l_execution(monkeypatch):
    """Un suppleant peut etre DECLARE en dur ou CONSTATE au run, avec sa date.

    MESURE 2026-09-17 : le meme rapport imprimait « pip-audit : non mesure —
    supplee par pip_audit_2026-09-16.json, 0.9 j » PUIS, trois lignes plus bas,
    « pip-audit : ANERGIQUE — aucun verdict reel depuis jamais » sans
    suppleant. `_anergie_detail` ne lisait que la table STATIQUE `_SUPPLEANTS`,
    alors que le suppleant de pip-audit est calcule au run (il porte la
    fraicheur du rapport). Deux chemins pour la meme information, un seul
    lisait la table — et l'ecran donnait le detail juste a cote d'un agregat nu.
    """
    monkeypatch.setattr(C, "_INCONCLUS",
                        [("pip-audit (dependances)", False,
                          "mesure deportee pip_audit_2026-09-16.json, 0.9 j")])
    detail = C._anergie_detail("pip-audit")
    assert "SUPPLEE" in detail, "le suppleant constate n'est pas nomme : %r" % detail
    assert "pip_audit_2026-09-16.json" in detail


def test_l_anergie_de_pip_audit_nomme_sa_cause_mesuree(monkeypatch):
    """Une anergie sans cause se relit comme une negligence. Celle-ci est
    STRUCTURELLE : la CI n'a pas d'egress, installer l'outil n'y changerait
    rien — il tourne, c'est la sortie reseau qui est refusee."""
    monkeypatch.setattr(C, "_INCONCLUS", [])
    detail = C._anergie_detail("pip-audit")
    assert "cause" in detail.lower()
    assert "10013" in detail or "egress" in detail.lower()


def test_une_cle_sans_cause_ni_suppleant_reste_VIDE(monkeypatch):
    """Rien n'est invente : sans mesure, le complement est vide. Une
    explication inventee est pire qu'une case vide, elle clot l'enquete."""
    monkeypatch.setattr(C, "_INCONCLUS", [])
    assert C._anergie_detail("gate-qui-n-existe-pas") == ""


def test_le_cliquet_est_ecrit_en_local(registre):
    C._summary([("flake8 critique (E9,F63,F7)", True)])
    fiche = json.loads(registre.read_text(encoding="utf-8"))["gardes"]["flake8 critique"]
    assert fiche["etat"] == "PASS" and fiche["dernier_reel"]


def test_le_cliquet_n_est_PAS_ecrit_en_CI(registre, monkeypatch):
    # Un arbre sali sur le runner rend le cliquet de mutation INDETERMINE :
    # le registre ne doit pas provoquer la panne qu'il est cense detecter.
    monkeypatch.setenv("CI", "true")
    C._summary([("flake8 critique (E9,F63,F7)", True)])
    assert not registre.exists()


# ---------------------------------------------------------------------------
# UNE ANERGIE SUPPLEEE N'EST PAS UN TROU (mesure 2026-09-16)
#
# `archi-lint` etait signale ANERGIQUE (domaine CRITIQUE) quatre fois dans la
# meme journee, sans qu'aucune action soit possible. MESURE de la cause :
# semgrep est INSTALLE (miniforge3/Scripts/semgrep.EXE) mais meurt au demarrage
# sous LaForgeSbxOffline ET LaForgeSbxOnline --
#   Fatal error: Failed to create system store X509 authenticator:
#   ca_certs_iter_on_anchors: CertOpenSystemStore returned NULL
# Les comptes de service n'ont pas de magasin de certificats utilisateur, et le
# plantage precede le traitement des options : SEMGREP_SEND_METRICS=off n'y
# change rien. L'anergie est donc STRUCTURELLE, pas une negligence.
#
# Et le domaine EST couvert : `_SUPPLEANTS` declare golden-rules (moteur AST
# natif, cliquet ERROR). Le message alarmait donc sur un domaine protege, sans
# dire la cause. Un garde qui crie a faux se fait desarmer -- c'est le faux
# positif qu'on corrige tout de suite, pas le signal qu'on supprime.
# ---------------------------------------------------------------------------


def test_une_anergie_SUPPLEEE_nomme_son_suppleant():
    detail = C._anergie_detail("archi-lint")
    assert "golden-rules" in detail, (
        "le message d'anergie ne dit pas que le domaine est SUPPLEE : il fait "
        "croire a un trou sur un domaine couvert"
    )


def test_une_anergie_dont_la_CAUSE_est_mesuree_la_nomme():
    detail = C._anergie_detail("archi-lint").lower()
    assert "semgrep" in detail, (
        "la cause mesuree n'apparait pas : le lecteur ne peut ni agir ni juger "
        "si l'anergie est reparable"
    )


def test_un_garde_sans_cause_ni_suppleant_n_INVENTE_rien():
    assert C._anergie_detail("garde_qui_n_existe_pas_nr") == "", (
        "un complement fabrique pour un garde inconnu ferait passer une "
        "ignorance pour une explication"
    )


def test_le_message_d_anergie_emprunte_bien_ce_detail():
    import inspect
    assert "_anergie_detail(" in inspect.getsource(C), (
        "la fonction est testee mais le message ne l'appelle pas — le NR serait "
        "vert sans rien changer a ce que la CI affiche"
    )
