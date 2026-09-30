"""NR -- les cliquets-outils de la CI (golden-rules, duplication) sont joues au PRE-PUSH, sur le SHA POUSSE.

Owner 2026-09-26 (« oui ajoute le ») : la CI de reference sur f6b3613bb est tombee sur deux cliquets -- golden
3 -> 4 et 3 groupes de clones -- venus de commits faits des jours plus tot. Ils se jouent en secondes ; ils ne
l'etaient qu'en CI complete, apres coup. Trois etats, jamais deux : OK, ROMPU (bloque), NON_MESURE (avertit sans
bloquer : un garde neuf qui crie sur une panne d'infra se fait desarmer, la CI reste le filet).
Sorties de fixture = lignes REELLES des CI du 26/09 (job_fe0e1514d913, job_c6301459720a).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_prepush_cliquets as pp  # noqa: E402

SHA = "8cf052a6c5345dab60fe89b552d197a1faa60b60"
NUL = "0" * 40
ROMPU_REEL = (
    "[golden_ast] CLIQUET ROMPU — 1 violation(s) ERROR nouvelle(s) :\n"
    "  + laforge-cloud-secret-from-env  app/forge_key_rotation.py  (3 -> 4)\n"
    "  → FAIL (rc=1, 19.0 s)\n"
    "  │ [golden_ast] CLIQUET ROMPU — 1 violation(s) ERROR nouvelle(s) :\n"
    "  │   + laforge-cloud-secret-from-env  app/forge_key_rotation.py  (3 -> 4)\n"
    "\x1b[1;31m1 gate(s) bloquant(s) en échec — NE PAS pousser.\x1b[0m\n")
OK_REEL = "\x1b[1;32mTous les gates bloquants passent\x1b[0m \x1b[1;33m(1 non mesure(s), tous supplees)\x1b[0m\n"


def test_seuls_les_shas_pousses_sont_juges_et_une_suppression_est_ignoree():
    stdin = ("refs/heads/alpha %s refs/heads/alpha %s\n" % (SHA, "a" * 40)
             + "(delete) %s refs/heads/vieille %s\n" % (NUL, "b" * 40)
             + "refs/heads/alpha %s refs/heads/autre %s\n" % (SHA, NUL))
    assert pp.shas_a_verifier(stdin) == [SHA]


def test_la_commande_juge_le_sha_pousse_dans_un_worktree_detache():
    cmd = pp.commande(SHA, python="py")
    assert cmd[0] == "py" and cmd[1].endswith("ci_local.py")
    assert cmd[2:] == ["--only", "golden-rules", "--only", "duplication", "--reference", SHA]


def test_trois_etats_sur_des_sorties_reelles():
    assert pp.classer(OK_REEL) == pp.OK
    assert pp.classer(ROMPU_REEL) == pp.ROMPU
    assert pp.classer("lancement impossible : FileNotFoundError") == pp.NON_MESURE
    assert pp.classer("") == pp.NON_MESURE


def test_un_cliquet_rompu_bloque_et_nomme_la_violation(capsys):
    rc = pp.main(stdin_text="refs/heads/alpha %s refs/heads/alpha %s\n" % (SHA, NUL),
                 lancer=lambda cmd: (1, ROMPU_REEL))
    err = capsys.readouterr().err
    assert rc == 1
    assert "forge_key_rotation.py" in err and "BLOQUE" in err
    assert err.count("forge_key_rotation.py") == 1, "violation dite deux fois (echo « │ » de ci_local)"


def test_non_mesure_avertit_sans_bloquer(capsys):
    rc = pp.main(stdin_text="refs/heads/alpha %s refs/heads/alpha %s\n" % (SHA, NUL),
                 lancer=lambda cmd: (None, "lancement impossible : OSError"))
    assert rc == 0 and "NON MESURE" in capsys.readouterr().err


def test_vert_laisse_passer_et_une_suppression_seule_ne_lance_rien():
    appels = []
    assert pp.main(stdin_text="refs/heads/alpha %s refs/heads/alpha %s\n" % (SHA, NUL),
                   lancer=lambda cmd: appels.append(cmd) or (0, OK_REEL)) == 0
    assert len(appels) == 1
    assert pp.main(stdin_text="(delete) %s refs/heads/x %s\n" % (NUL, SHA),
                   lancer=lambda cmd: appels.append(cmd) or (0, OK_REEL)) == 0
    assert len(appels) == 1


def test_le_hook_pre_push_joue_les_cliquets_avant_l_egress_et_lui_rend_le_stdin():
    # Chemin reel : le shim versionne `.githooks/pre-push` (core.hooksPath) lit stdin UNE fois, lance les
    # cliquets, puis transmet ce meme stdin au filtre d'egress -- sinon l'egress lirait un stdin deja vide.
    src = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    # Les CHEMINS construits par le code, pas les noms : l'en-tete du shim cite forge_git_egress en commentaire.
    cliquets = 'os.path.join(root, "tools", "forge_prepush_cliquets.py")'
    egress = 'os.path.join(root, "app", "forge_git_egress.py")'
    assert cliquets in src and egress in src
    assert src.index(cliquets) < src.index(egress)
    assert "input=data" in src and "dup2" in src
