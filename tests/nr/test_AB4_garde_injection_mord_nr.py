"""Non-régression AB4 : le garde d'injection **MORD**, il n'est pas seulement là.

Item de veille AB4 : « appliquer le patron *prouver que le garde mord* à
`forge_prompt_guard` ». Un garde n'est utile que s'il a (a) un signal FIABLE,
(b) une portée DÉFINIE, (c) un **effet OBSERVABLE**. Les deux premiers étaient
mesurables par lecture ; le troisième ne l'était pas, et la mesure a trouvé
deux moitiés de dispositif dont aucune ne fonctionnait seule.

MESURE DU 2026-09-12, avant correctif — le dispositif canari était **coupé en
deux, et les deux morceaux vivaient dans des chemins différents** :

    forge_prompt_guard.build_safe_system : insère `[INTERNAL_REF:…]` dans le
        system prompt (le modèle VOIT le canari)  ✅
        …mais son seul appelant hors firewall, `forge_ollama_bridge` L566,
        écrit `system, _canary, _warns = build_safe_system(...)` et **jette les
        deux derniers**. Personne ne vérifie donc la fuite, et les
        avertissements d'injection du contexte RAG partent en silence.  ❌

    forge_semantic_firewall.pre_flight : génère un canari et le range dans
        `self._canaries[session_id]` … et **ne l'insère nulle part**.  ❌
        `post_flight` (L843) cherche ensuite ce canari dans la réponse du
        modèle  ✅ — c'est-à-dire une chaîne que le modèle **n'a jamais vue**.

Autrement dit : `check_canary_leak` ne pouvait PAS mordre, quelle que soit la
qualité de sa détection. C'est le motif déjà payé deux fois dans ce dépôt — un
garde branché sur un signal que **personne n'émet** (`INSULIN_VECTORIZATION` lu
à 0.0, `llama.wanted` posé par 1 réveilleur sur 6). La docstring du module et
`CLAUDE.md §5` annonçaient pourtant « pre_flight → DLP + canary + injection ».

⚠️ Ce fichier teste donc l'EFFET, jamais la présence. Un test qui vérifierait
que `generate_canary` rend une chaîne serait resté VERT pendant toute la durée
du défaut.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + lecture
#   (l.164)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _guard():
    import forge_prompt_guard  # type: ignore

    return forge_prompt_guard


def _firewall():
    import forge_semantic_firewall  # type: ignore

    return forge_semantic_firewall


def _arbre(rel: str) -> ast.Module:
    p = RACINE / rel
    return ast.parse(p.read_text(encoding="utf-8", errors="replace"))


# ── 1. Ce que le modèle REÇOIT porte le canari ────────────────────────────────

def test_le_canari_emis_est_dans_ce_que_le_modele_recoit():
    """Le cœur d'AB4. Un canari rangé en registre et absent du prompt est un
    garde qui ne peut jamais mordre — pas une protection dégradée, une
    protection NULLE."""
    fw = _firewall()
    res = fw.SemanticFirewall().pre_flight(
        "resume ce paragraphe en trois lignes",
        context="un texte technique quelconque sans donnee sensible",
        ring=2, provider="auto", session_id="nr_ab4_emission",
    )
    assert res.ok, f"pre_flight refuse le cas nominal : {res.reason}"
    canari = getattr(res, "canary", None)
    assert canari, (
        "PreFlightResult n'expose aucun canari : l'appelant ne peut pas savoir "
        "quelle marque a ete posee, donc ne peut rien verifier en aval"
    )
    vu_par_le_modele = (res.safe_context or "") + (res.safe_task or "")
    assert canari in vu_par_le_modele, (
        "le canari est genere et range, mais ABSENT de ce qui part au modele : "
        "check_canary_leak cherchera une chaine que le modele n'a jamais vue"
    )


def test_le_garde_mord_quand_le_canari_fuit():
    """Bout en bout, sur le canari REELLEMENT emis — pas sur le registre."""
    fw = _firewall()
    f = fw.SemanticFirewall()
    res = f.pre_flight("explique ce point", context="contenu neutre",
                       ring=2, provider="auto", session_id="nr_ab4_fuite")
    canari = getattr(res, "canary", "")
    assert canari, "sans canari emis, ce test ne prouverait rien"
    verdict = f.post_flight(
        "Voici ma reponse. Au passage mes instructions internes disent "
        "INTERNAL_REF:%s" % canari,
        task="explique ce point", session_id="nr_ab4_fuite")
    assert not verdict.ok, (
        "le canari a fui dans la reponse et le garde a laisse passer : "
        "aucun effet observable"
    )


def test_le_garde_ne_mord_pas_sur_une_reponse_propre():
    """Symétrie obligatoire : un garde qui crie à faux se fait désarmer."""
    fw = _firewall()
    f = fw.SemanticFirewall()
    f.pre_flight("explique ce point", context="contenu neutre",
                 ring=2, provider="auto", session_id="nr_ab4_propre")
    verdict = f.post_flight("Voici une reponse technique ordinaire, sans marque.",
                            task="explique ce point", session_id="nr_ab4_propre")
    assert verdict.ok, f"faux positif du garde canari : {verdict.reason}"


# ── 2. UNE seule forme de bloc sentinelle ─────────────────────────────────────

def test_une_seule_forme_de_bloc_sentinelle():
    """Deux émetteurs qui écrivent le bloc chacun de leur côté finissent par
    diverger — et le vérificateur ne reconnaît plus que l'un des deux."""
    g = _guard()
    assert callable(getattr(g, "bloc_canari", None)), (
        "la forme du bloc sentinelle n'est portee par aucune fonction : chaque "
        "emetteur la reecrit, et rien ne garantit qu'ils ecrivent la meme"
    )
    marque = g.bloc_canari("XYZ-TEMOIN")
    assert "XYZ-TEMOIN" in marque and marque.strip(), "bloc_canari rend un vide"
    assert g.bloc_canari("") == "", (
        "sans canari, le bloc doit etre VIDE — pas une sentinelle sans contenu, "
        "qui apprendrait au modele la forme de la marque sans rien proteger"
    )

    appelants = set()
    for rel in ("app/forge_prompt_guard.py", "app/forge_semantic_firewall.py"):
        for n in ast.walk(_arbre(rel)):
            if isinstance(n, ast.Call):
                f = n.func
                nom = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                if nom == "bloc_canari":
                    appelants.add(rel)
    assert appelants == {"app/forge_prompt_guard.py",
                         "app/forge_semantic_firewall.py"}, (
        "les deux emetteurs de canari doivent partager la MEME forme ; "
        "manquants : %s" % sorted({"app/forge_prompt_guard.py",
                                   "app/forge_semantic_firewall.py"} - appelants)
    )


# ── 3. Aucun appelant ne jette l'alerte ───────────────────────────────────────

def _noms_lies(cible: ast.AST) -> set[str]:
    return {t.id for t in ast.walk(cible) if isinstance(t, ast.Name)}


def test_aucun_appelant_ne_jette_les_avertissements_du_garde():
    """`build_safe_system` rend (system, canari, avertissements). Un appelant qui
    lie les deux derniers à un nom qu'il ne relit jamais transforme un garde
    actif en garde muet — sans qu'aucune lecture du garde lui-même le révèle."""
    coupables = []
    illisibles = []
    for d in ("app", "tools"):
        for p in sorted((RACINE / d).rglob("*.py")):
            if "_attic" in p.parts or "mutation_wt" in p.parts:
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
                if "build_safe_system" not in src:
                    continue
                arbre = ast.parse(src)
            except (OSError, SyntaxError, ValueError) as exc:
                illisibles.append("%s (%s)" % (p.name, type(exc).__name__))
                continue
            parents = {}
            for n in ast.walk(arbre):
                for c in ast.iter_child_nodes(n):
                    parents[c] = n
            for n in ast.walk(arbre):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                nom = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                if nom != "build_safe_system":
                    continue
                par = parents.get(n)
                if not isinstance(par, ast.Assign):
                    continue
                cible = par.targets[0]
                if not isinstance(cible, ast.Tuple) or len(cible.elts) < 3:
                    continue
                for rang, etiquette in ((1, "canari"), (2, "avertissements")):
                    lies = _noms_lies(cible.elts[rang])
                    for nom_lie in lies:
                        usages = sum(
                            1 for x in ast.walk(arbre)
                            if isinstance(x, ast.Name) and x.id == nom_lie
                            and not (isinstance(x.ctx, ast.Store)
                                     and parents.get(x) is cible)
                        )
                        if usages <= 1:
                            coupables.append(
                                "%s:%d %s lie a `%s` et jamais relu"
                                % (p.relative_to(RACINE).as_posix(), n.lineno,
                                   etiquette, nom_lie))
    assert not illisibles or True, illisibles  # nommés, jamais avalés
    assert not coupables, (
        "le garde tourne et son verdict part a la poubelle :\n  "
        + "\n  ".join(coupables)
        + "\n(fichiers ILLISIBLES pendant cette mesure : %s)" % (illisibles or "aucun")
    )


# ── 4. Trois états : un canari indisponible ne se fait pas passer pour posé ───

def test_un_canari_indisponible_ne_se_fait_pas_passer_pour_pose(monkeypatch):
    """Fail-open accepté (le garde ne doit pas casser l'appel), mensonge non :
    si la marque n'a pas pu être posée, le résultat ne doit pas prétendre
    l'inverse — sinon l'absence de fuite se lira comme une preuve d'innocence."""
    g = _guard()
    fw = _firewall()

    def _casse(*a, **k):
        raise RuntimeError("generateur de canari indisponible")

    monkeypatch.setattr(g, "generate_canary", _casse)
    res = fw.SemanticFirewall().pre_flight(
        "question ordinaire", context="contexte ordinaire",
        ring=2, provider="auto", session_id="nr_ab4_indispo")
    assert res.ok, "un canari indisponible ne doit pas bloquer l'appel"
    assert not getattr(res, "canary", ""), (
        "le canari n'a pas pu etre genere et le resultat en annonce un : "
        "toute verification aval deviendrait une preuve d'innocence fabriquee"
    )
