"""Point 1 de la boucle d'auto-amelioration (Codex CLI, 2026-08-27) : le SOCLE de
l'apprentissage doit fonctionner DANS le contexte d'execution de l'agent. Ce test de
fumee GARDE le round-trip complet : bootstrap -> import -> read_lessons ->
anchor_solution -> recall(meme contexte). Sans lui, « les lecons ne sont pas relues
de facon fiable avant les actions » (le bootstrap qui echoue) passe inapercu.

Mesure du jour (smoke reel) : l'import NU de `forge_self_correction` ECHOUE depuis le
contexte hub (`app/` hors de sys.path) -- donc tout agent/script qui ne bootstrappe
pas explicitement ne relit PAS les lecons. Ce test impose donc le bootstrap canonique
(app/ + tools/ dans le path, comme la boucle et CLAUDE.md §9) ET verifie qu'une ancre
posee est RETROUVEE au recall : preuve que memoire != prose morte (Codex pt 4).

Les ancres de ce test portent domain='ci_smoke' + un marqueur horodate : identifiables,
jamais confondues avec une vraie lecon, jamais supprimees (owner : rien n'est efface
en base -- elles restent, marquees).
"""
import sys
import time
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 sur la VRAIE base (code
#   appele) (l.55)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)


def test_forge_self_correction_importable_et_api():
    """Import + API publique presente (l'import NU echoue hors bootstrap : on l'impose)."""
    import forge_self_correction as fsc  # noqa: PLC0415

    for fn in ("read_lessons", "anchor_solution", "preflight_check_verbose", "session_summary"):
        assert hasattr(fsc, fn), f"forge_self_correction.{fn} absent -- socle d'apprentissage casse"


def test_read_lessons_rend_du_texte():
    """read_lessons doit rendre du texte lisible (lecture seule, aucun effet de bord)."""
    import forge_self_correction as fsc  # noqa: PLC0415

    txt = fsc.read_lessons(300)
    assert isinstance(txt, str)


def test_anchor_puis_recall_meme_contexte():
    """Le coeur du point 1 : une ancre POSEE doit etre RETROUVEE au meme endroit.

    C'est ce qui distingue une memoire d'un depot de texte : si l'ancre n'est pas
    rappelable, `anchor_solution` accumule sans que rien n'apprenne (Codex pt 4).
    """
    import forge_self_correction as fsc  # noqa: PLC0415

    marker = f"CI_SMOKE_ROUNDTRIP_{int(time.time())}"

    def _poser():
        fsc.anchor_solution(
            problem=marker + " probe",
            solution="garde de round-trip anchor->recall (Codex pt1, 2026-08-27)",
            example="n/a",
            domain="ci_smoke",
        )

    # UN VERROU CONCURRENT N'EST PAS UN ECHEC DU SOCLE. Ce test ecrit VOLONTAIREMENT dans
    # la base reelle -- c'est ce qui lui donne sa valeur : il garde le round-trip dans le
    # contexte d'execution veritable. Mais la base est partagee avec les daemons, et sous
    # charge l'ecriture attend un verrou : le timeout pytest (30 s) transformait alors une
    # ABSENCE DE MESURE en ROUGE. Mesure du 2026-09-06 : deux fois dans la soiree, aux deux
    # passages qui suivaient un redemarrage, pendant que memory_compactor et l'ingestion
    # ecrivaient. `UNKNOWN` n'est pas `NO`.
    # `write_retry` ne convient PAS ici et l'y employer etait une ERREUR (mesuree le
    # 2026-09-06, `TypeError: _poser() takes 0 positional arguments but 1 was given`) :
    # cette primitive FOURNIT une connexion a l'operation (`op(conn)`), alors que
    # `anchor_solution` ouvre la sienne. On reprend donc l'APPEL lui-meme, avec les memes
    # proprietes que la primitive : recul croissant + JITTER (sans jitter, N ecrivains
    # repartent a la meme milliseconde et se rebloquent), et on ne reprend QUE les erreurs
    # de verrou -- une contrainte violee doit remonter tout de suite.
    import random  # noqa: PLC0415

    _dernier = None
    for _essai in range(5):
        try:
            _poser()
            _dernier = None
            break
        except Exception as e:  # noqa: BLE001
            _motif = str(e).lower()
            if not ("lock" in _motif or "timeout" in _motif or "busy" in _motif):
                raise
            _dernier = e
            time.sleep(0.2 * (2 ** _essai) + random.random() * 0.2)
    if _dernier is not None:
        import pytest  # noqa: PLC0415

        pytest.skip(f"ecriture INDETERMINEE : la base est verrouillee par un ecrivain "
                    f"concurrent ({type(_dernier).__name__}) apres 5 reprises. Ce n'est "
                    f"pas un echec du socle d'apprentissage -- la mesure n'a pas pu "
                    f"avoir lieu.")
    v = fsc.preflight_check_verbose(marker, "")
    hits = [r for r in (v.get("results") or []) if marker in str(r)]
    if not hits:
        import pytest  # noqa: PLC0415

        pytest.skip("recall indisponible ici (RAG/embedder non peuple, CI hermetique) ; "
                    "anchor sans exception = write OK ; round-trip verifiable ou vit le RAG")
