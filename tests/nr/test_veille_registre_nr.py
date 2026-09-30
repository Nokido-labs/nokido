"""NR — le registre de veille doit etre fail-closed, deterministe et verifiable.

Trois modules sous contrat : `forge_veille_registre` (le contrat lui-meme),
`forge_veille_clone_ingest` (le consommateur) et `forge_veille_backlog_github`
(le producteur). `forge_veille_intake_filter` est couvert par l'effet de son
filtre, dont depend l'etat READY/STALE d'un dump.

Les modes de panne testes ici ont tous ete PAYES ou identifies sur le terrain :

  - un registre absent qui redevient 12 depots en silence, alors que la campagne
    en compte 342 : un rapport de succes sur 3,5 % du travail ;
  - une faute de frappe qui, la liste filtree devenant vide, declenchait la
    campagne ENTIERE ;
  - un dump juge sur sa TAILLE, donc ingere sans qu'on sache de quel commit il
    vient — une connaissance qu'on ne peut pas re-verifier est une croyance ;
  - un ordre de lot recalcule a chaque lancement, qui fait glisser le « lot 3 »
    d'une passe a l'autre ;
  - `write_text()` sur le fichier final : un plantage au milieu laisse un JSON
    ampute mais syntaxiquement valide, que le lecteur consommerait.

Tests PURS : aucun reseau, aucune base, aucun clone. Tout passe par `tmp_path`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))

# Le contrat s'importe sous le MEME nom que dans les modules testes
# (`forge_veille_registre`, PAS `tools.forge_veille_registre`). Deux chemins
# d'import donnent DEUX objets module, donc deux classes `RegistreInvalide`
# distinctes -- et `pytest.raises` ne rattrape alors rien, l'exception traverse
# le test. Piege paye ici meme, au premier lancement.
import forge_veille_registre as reg  # noqa: E402
from forge_veille_intake_filter import FILTRE_VERSION, est_genere  # noqa: E402
from tools import forge_veille_backlog_github as backlog  # noqa: E402
from tools import forge_veille_clone_ingest as ingest  # noqa: E402


# ── fabriques ───────────────────────────────────────────────────────────────
def _entrees(*repos, priorite="demande"):
    return [{"repo": r, "priorite": priorite, "mentions_owner": i,
             "mentions_agent": 0, "premiere_demande": "2026-07-01",
             "origine": "conv", "etat": "ABSENT", "detail": "-"}
            for i, r in enumerate(repos)]


def _doc(*repos, priorite="demande"):
    return reg.construire_registre(_entrees(*repos, priorite=priorite),
                                   source="test", generated_at="2026-08-31T00:00:00+00:00")


def _ecrit(chemin, doc):
    reg.ecrire_atomique(chemin, json.dumps(doc, ensure_ascii=False))
    return chemin


# ── 1. registre valide ──────────────────────────────────────────────────────
def test_registre_valide_est_accepte_et_expose_ses_cibles(tmp_path):
    p = _ecrit(tmp_path / "r.json", _doc("a/un", "b/deux"))
    cibles = ingest.charger_cibles(p)
    assert set(c["repo"] for c in cibles.values()) == {"a/un", "b/deux"}
    assert all(c["url"].startswith("https://github.com/") for c in cibles.values())


def test_generation_id_est_l_empreinte_du_contenu(tmp_path):
    """Deux generations sur les MEMES donnees rendent le meme id.

    C'est ce qui permet a une campagne de constater qu'elle travaille toujours
    sur le meme instantane. Un horodatage ou un aleatoire ne le permettrait pas.
    """
    a = _doc("a/un", "b/deux")
    b = _doc("a/un", "b/deux")
    assert a["generation_id"] == b["generation_id"]
    assert _doc("a/un", "c/trois")["generation_id"] != a["generation_id"]


# ── 2-7. registre degrade : TOUJOURS un refus, jamais un repli ──────────────
def test_registre_absent_est_refuse(tmp_path):
    with pytest.raises(reg.RegistreInvalide, match="ABSENT"):
        reg.charger_registre(tmp_path / "nexiste_pas.json")


def test_registre_json_corrompu_est_refuse(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{ceci n'est pas du json", encoding="utf-8")
    with pytest.raises(reg.RegistreInvalide, match="corrompu"):
        reg.charger_registre(p)


def test_schema_invalide_champ_absent_est_refuse(tmp_path):
    doc = _doc("a/un")
    doc.pop("generated_at")
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="generated_at"):
        reg.charger_registre(p)


def test_schema_version_inattendue_est_refusee(tmp_path):
    doc = _doc("a/un")
    doc["schema_version"] = 999
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="schema_version"):
        reg.charger_registre(p)


def test_mentions_owner_non_entier_est_refuse(tmp_path):
    doc = _doc("a/un")
    list(doc["cibles"].values())[0]["mentions_owner"] = "beaucoup"
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="mentions_owner"):
        reg.charger_registre(p)


def test_mentions_owner_booleen_est_refuse(tmp_path):
    """`True` est un `int` en Python : sans garde, il passerait pour 1."""
    doc = _doc("a/un")
    list(doc["cibles"].values())[0]["mentions_owner"] = True
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="mentions_owner"):
        reg.charger_registre(p)


def test_cibles_de_mauvais_type_est_refuse(tmp_path):
    doc = _doc("a/un")
    doc["cibles"] = ["a/un"]
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="cibles"):
        reg.charger_registre(p)


def test_compteur_incoherent_trahit_un_registre_ampute(tmp_path):
    doc = _doc("a/un", "b/deux")
    doc["cibles"].pop(next(iter(doc["cibles"])))   # ecriture interrompue
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="count"):
        reg.charger_registre(p)


def test_url_incoherente_avec_le_repo_est_refusee(tmp_path):
    doc = _doc("a/un")
    list(doc["cibles"].values())[0]["url"] = "https://github.com/autre/depot"
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide):
        reg.charger_registre(p)


def test_collision_d_identite_est_refusee(tmp_path):
    """Deux slugs qui pointent le meme depot se disputeraient le meme dump."""
    doc = _doc("a/un")
    cible = dict(list(doc["cibles"].values())[0])
    cible["ordinal"] = 1
    doc["cibles"]["un_autre_slug"] = cible
    doc["count"] = 2
    doc["generation_id"] = reg.calcul_generation_id(doc["cibles"])
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="collision d'identite"):
        reg.charger_registre(p)


def test_ordinal_partage_est_refuse(tmp_path):
    doc = _doc("a/un", "b/deux")
    for c in doc["cibles"].values():
        c["ordinal"] = 0
    doc["generation_id"] = reg.calcul_generation_id(doc["cibles"])
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="ordinal"):
        reg.charger_registre(p)


def test_generation_id_retouche_est_detectee(tmp_path):
    doc = _doc("a/un", "b/deux")
    doc["generation_id"] = "0" * 16
    p = _ecrit(tmp_path / "r.json", doc)
    with pytest.raises(reg.RegistreInvalide, match="generation_id"):
        reg.charger_registre(p)


# ── fail-closed cote consommateur ───────────────────────────────────────────
def test_registre_absent_ne_bascule_PAS_sur_les_12_historiques(tmp_path):
    """Le mode de panne central : 342 cibles qui redeviennent 12 en silence."""
    with pytest.raises(reg.RegistreInvalide):
        ingest.charger_cibles(tmp_path / "absent.json")


def test_le_repli_legacy_existe_mais_se_demande(tmp_path):
    cibles = ingest.charger_cibles(tmp_path / "absent.json", allow_legacy=True)
    assert len(cibles) == len(ingest.REPOS)
    assert all("target_id" in c and "nom_dump" in c for c in cibles.values())


# ── 9. ecriture atomique ────────────────────────────────────────────────────
def test_ecriture_atomique_ne_laisse_aucun_temporaire(tmp_path):
    p = reg.ecrire_atomique(tmp_path / "x.json", '{"ok": 1}')
    assert p.read_text(encoding="utf-8") == '{"ok": 1}'
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_ecriture_interrompue_laisse_l_ancien_contenu_INTACT(tmp_path, monkeypatch):
    """Le point de l'atomicite : jamais de contenu a moitie ecrit.

    `write_text()` tronque AVANT d'ecrire : le lecteur suivant trouverait un
    fichier ampute. Ici l'ancien contenu survit, et aucun temporaire ne traine.
    """
    cible = tmp_path / "x.json"
    cible.write_text("ANCIEN", encoding="utf-8")

    def _replace_casse(*_a, **_k):
        raise OSError("disque plein")

    monkeypatch.setattr(reg.os, "replace", _replace_casse)
    with pytest.raises(OSError):
        reg.ecrire_atomique(cible, "NOUVEAU")
    assert cible.read_text(encoding="utf-8") == "ANCIEN"
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_ecrire_registre_refuse_de_publier_un_document_invalide(tmp_path):
    doc = _doc("a/un")
    doc["count"] = 99
    with pytest.raises(reg.RegistreInvalide):
        reg.ecrire_registre(tmp_path / "r.json", doc)
    assert not (tmp_path / "r.json").exists()


# ── 10-11. selection : une faute de frappe n'est PAS « tout » ───────────────
def test_cible_inconnue_est_une_erreur_et_ne_selectionne_RIEN(tmp_path):
    cibles = ingest.charger_cibles(_ecrit(tmp_path / "r.json", _doc("a/un", "b/deux")))
    with pytest.raises(ingest.CibleInconnue):
        ingest.selectionner(cibles, ["a_un_typo"])


def test_sans_argument_toutes_les_cibles_sont_retenues(tmp_path):
    cibles = ingest.charger_cibles(_ecrit(tmp_path / "r.json",
                                          _doc("a/un", "b/deux", "c/trois")))
    assert len(ingest.selectionner(cibles, [])) == 3


def test_une_cible_connue_parmi_des_options_est_bien_isolee(tmp_path):
    doc = _doc("a/un", "b/deux")
    cibles = ingest.charger_cibles(_ecrit(tmp_path / "r.json", doc))
    slug = [s for s, c in cibles.items() if c["repo"] == "b/deux"][0]
    assert ingest.selectionner(cibles, [slug, "--dump-only", "--force"]) == [slug]


def test_la_valeur_d_une_option_n_est_pas_prise_pour_une_cible(tmp_path):
    """`--lot 2` : le `2` ne doit pas etre lu comme un nom de depot."""
    cibles = ingest.charger_cibles(_ecrit(tmp_path / "r.json",
                                          _doc("a/un", "b/deux", "c/trois")))
    assert ingest.positionnels(["--lot", "2", "--dump-only"]) == []
    assert len(ingest.selectionner(cibles, ["--lot", "2"])) == 2


# ── 12. lots deterministes ──────────────────────────────────────────────────
def test_lots_deterministes_et_sans_recouvrement(tmp_path):
    cibles = ingest.charger_cibles(_ecrit(
        tmp_path / "r.json", _doc("a/un", "b/deux", "c/trois", "d/quatre")))
    lot1 = ingest.selectionner(cibles, ["--lot=2", "--depuis=0"])
    lot2 = ingest.selectionner(cibles, ["--lot=2", "--depuis=2"])
    assert lot1 == ingest.selectionner(cibles, ["--lot=2", "--depuis=0"])
    assert not set(lot1) & set(lot2)
    assert lot1 + lot2 == ingest.selectionner(cibles, [])


def test_l_ordre_suit_l_ordinal_du_registre_pas_l_alphabet(tmp_path):
    """Le registre FIGE l'ordre ; le consommateur ne re-derive rien."""
    cibles = ingest.charger_cibles(_ecrit(tmp_path / "r.json",
                                          _doc("z/dernier", "a/premier")))
    ordre = ingest.selectionner(cibles, [])
    assert cibles[ordre[0]]["repo"] == "z/dernier"


def test_filtre_par_priorite(tmp_path):
    doc = reg.construire_registre(
        _entrees("a/un", priorite="demande") + _entrees("b/deux", priorite="contexte"),
        source="test", generated_at="2026-08-31T00:00:00+00:00")
    cibles = ingest.charger_cibles(_ecrit(tmp_path / "r.json", doc))
    choisis = ingest.selectionner(cibles, ["--priorite=contexte"])
    assert [cibles[s]["repo"] for s in choisis] == ["b/deux"]


# ── 13. instantane de campagne ──────────────────────────────────────────────
def test_instantane_de_campagne_survit_a_la_regeneration_d_un_autre_registre(tmp_path):
    """Une campagne en cours ne doit pas voir ses lots glisser.

    Registre A fige la campagne. Un registre B, genere ailleurs avec d'autres
    cibles, ne doit ni redistribuer l'ordre ni etre accepte en silence.
    """
    a = ingest.charger_cibles(_ecrit(tmp_path / "a.json", _doc("a/un", "b/deux")))
    gen_a = reg.calcul_generation_id(a)
    snap = tmp_path / "campagne.json"
    ordre_a = ingest.snapshot_campagne(snap, sorted(a, key=lambda s: a[s]["ordinal"]),
                                       gen_a)
    avant = snap.read_text(encoding="utf-8")

    b = ingest.charger_cibles(_ecrit(tmp_path / "b.json", _doc("c/trois", "d/quatre")))
    gen_b = reg.calcul_generation_id(b)
    assert gen_b != gen_a
    with pytest.raises(reg.RegistreInvalide, match="campagne figee"):
        ingest.snapshot_campagne(snap, sorted(b), gen_b)
    assert snap.read_text(encoding="utf-8") == avant
    assert ingest.snapshot_campagne(snap, [], gen_a) == ordre_a


def test_instantane_prime_sur_l_ordre_courant(tmp_path):
    a = ingest.charger_cibles(_ecrit(tmp_path / "a.json", _doc("a/un", "b/deux")))
    gen = reg.calcul_generation_id(a)
    ordre = sorted(a, key=lambda s: a[s]["ordinal"])
    snap = tmp_path / "c.json"
    ingest.snapshot_campagne(snap, ordre, gen)
    fige = ingest.snapshot_campagne(snap, list(reversed(ordre)), gen)
    assert fige == ordre
    assert ingest.selectionner(a, ["--lot=1"], ordre_fige=fige)[0] == ordre[0]


# ── 14-16. etat d'un dump : ABSENT / STALE / READY ──────────────────────────
def _cible(repo="a/un"):
    url = reg.url_canonique(repo)
    return {"repo": repo, "url": url, "target_id": reg.target_id(url)}


def test_dump_absent(tmp_path):
    etat, _ = reg.etat_dump(tmp_path / "d.txt", _cible(), FILTRE_VERSION)
    assert etat == reg.ABSENT


def test_dump_trop_petit_est_absent_pas_pret(tmp_path):
    d = tmp_path / "d.txt"
    d.write_text("x", encoding="utf-8")
    etat, _ = reg.etat_dump(d, _cible(), FILTRE_VERSION)
    assert etat == reg.ABSENT


def test_dump_sans_manifeste_est_perime_jamais_pret(tmp_path):
    """Juger un dump sur sa TAILLE, c'est ingerer sans connaitre sa source."""
    d = tmp_path / "d.txt"
    d.write_text("x" * 5000, encoding="utf-8")
    etat, raison = reg.etat_dump(d, _cible(), FILTRE_VERSION)
    assert etat == reg.STALE and "provenance" in raison


def test_dump_sans_commit_source_est_perime(tmp_path):
    d = tmp_path / "d.txt"
    d.write_text("x" * 5000, encoding="utf-8")
    c = _cible()
    reg.ecrire_atomique(reg.chemin_manifeste(d), json.dumps(
        {"commit": "inconnu", "url": c["url"], "target_id": c["target_id"],
         "filtre_version": FILTRE_VERSION}))
    etat, raison = reg.etat_dump(d, c, FILTRE_VERSION)
    assert etat == reg.STALE and "commit" in raison


def test_dump_produit_par_un_filtre_anterieur_est_perime(tmp_path):
    d = tmp_path / "d.txt"
    d.write_text("x" * 5000, encoding="utf-8")
    c = _cible()
    reg.ecrire_atomique(reg.chemin_manifeste(d), json.dumps(
        {"commit": "abc123", "url": c["url"], "target_id": c["target_id"],
         "filtre_version": "0"}))
    etat, _ = reg.etat_dump(d, c, FILTRE_VERSION)
    assert etat == reg.STALE


def test_dump_d_un_autre_depot_est_perime(tmp_path):
    d = tmp_path / "d.txt"
    d.write_text("x" * 5000, encoding="utf-8")
    autre = _cible("b/deux")
    reg.ecrire_atomique(reg.chemin_manifeste(d), json.dumps(
        {"commit": "abc123", "url": autre["url"], "target_id": autre["target_id"],
         "filtre_version": FILTRE_VERSION}))
    etat, _ = reg.etat_dump(d, _cible("a/un"), FILTRE_VERSION)
    assert etat == reg.STALE


def test_dump_ready(tmp_path):
    d = tmp_path / "d.txt"
    d.write_text("x" * 5000, encoding="utf-8")
    c = _cible()
    reg.ecrire_atomique(reg.chemin_manifeste(d), json.dumps(
        {"commit": "abc123def456", "url": c["url"], "target_id": c["target_id"],
         "filtre_version": FILTRE_VERSION}))
    etat, raison = reg.etat_dump(d, c, FILTRE_VERSION)
    assert etat == reg.READY and "abc123def456" in raison


# ── 17. portabilite ─────────────────────────────────────────────────────────
def test_aucun_chemin_windows_code_en_dur_hors_windows(monkeypatch):
    monkeypatch.delenv("NOKIDO_VEILLE_SCRIPT_DIRS", raising=False)
    monkeypatch.setattr(os, "name", "posix")
    sources = backlog._sources_scripts()
    assert not any(str(p).lower().startswith("c:/tmp") for p in sources)