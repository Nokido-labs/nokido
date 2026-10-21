"""NR -- les trois sous-commandes de l'archive chiffree en flux.

ROADMAP p1_archive_chiffree_flux_2026-10-14, phase 2 : `tools/forge_backup_hotswap.py`
doit exposer `archive-flux`, `archive-verifier` et `archive-restaurer`. Mesure sur le
CHEMIN REEL : `main()` avec `sys.argv`, jamais l'appel direct d'une fonction dediee.

Trois proprietes, chacune rouge si on la casse :
  1. ALLER-RETOUR : une base synthetique (table ordinaire + BLOB + FTS5) est archivee
     chiffree puis restauree dans une base NEUVE -- le contenu ordinaire revient octet
     pour octet et le FTS reconstruit repond au MATCH ;
  2. REFUS : une archive dont UNE part a ete reecrite (manifeste intact, empreinte
     differente) est REFUSEE par `archive-verifier` -- rc non nul ;
  3. GARDE : `archive-restaurer` refuse une destination existante, jamais par-dessus.

Correction apres relecture du commit 47eb607af -- trois defauts, chacun un test qui
ne peut passer qu'une fois le code corrige :
  4. FTS ALIMENTE PAR UN TRIGGER : le schema complet (trigger compris) etait applique
     AVANT les donnees, puis le contenu archive de la table FTS etait reinsere -- chaque
     ligne indexee deux fois (`COUNT(*)` = 6 au lieu de 3, MATCH = 2 lignes au lieu de 1) ;
  5. WITHOUT ROWID : `SELECT rowid, *` plante sur une table sans rowid ;
  6. HACK DE CHARGEMENT : le module ne doit plus s'amorcer lui-meme dans `sys.modules`
     (c'est au chargeur du test de l'enregistrer avant `exec_module`).

py7zr absent de l'interpreteur : SKIP DIT (« py7zr absent : mesure impossible »), jamais
un vert. Aucun secret reel : `_cle_archive` est substitue par une cle de test ; aucune
base reelle : tout vit sous `tmp_path` ; aucun service, aucun reseau.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("py7zr", reason="py7zr absent : mesure impossible (jamais un vert muet)")

pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
CLE_DE_TEST = "cle-de-test-nr-archive-chiffree-flux"


def _charger_le_module():
    spec = importlib.util.spec_from_file_location(
        "forge_backup_hotswap_archive_flux_nr", ROOT / "tools" / "forge_backup_hotswap.py")
    mod = importlib.util.module_from_spec(spec)
    # Enregistre AVANT exec : dataclasses._is_type lit
    # sys.modules[cls.__module__].__dict__ sans garde -- un module jamais enregistre
    # ferait `None.__dict__` au premier @dataclass. C'est le CHARGEUR qui le fait,
    # pas le module (le hack d'amorce en production a ete retire).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod(monkeypatch):
    m = _charger_le_module()
    # Le coffre DPAPI n'est pas un instrument de test : la cle d'archive est substituee.
    # raising=False : au RED, `_cle_archive` n'existe pas encore -- c'est l'argparse qui
    # doit mordre en premier, pas la fixture.
    monkeypatch.setattr(m, "_cle_archive", lambda: CLE_DE_TEST, raising=False)
    return m


def _lance(mod, monkeypatch, *args: str) -> int:
    """Chemin reel : sous-commande posee sur sys.argv, puis main()."""
    monkeypatch.setattr(sys, "argv", ["forge_backup_hotswap.py", *args])
    return mod.main()


def _base(tmp_path: Path) -> Path:
    """Petite base synthetique : ordinaire + BLOB + compteur + FTS5."""
    src = tmp_path / "source.db"
    con = sqlite3.connect(src)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE fragments (id INTEGER PRIMARY KEY, titre TEXT, octets BLOB)")
    con.execute("CREATE TABLE compteur (n INTEGER)")
    con.execute("INSERT INTO compteur VALUES (3)")
    con.execute("CREATE VIRTUAL TABLE fragments_fts USING fts5(titre)")
    lignes = [
        ("memoire organisme", b"\x00\x01\xff" * 8),
        ("revocation cle", bytes(range(32))),
        ("archive en flux", None),
    ]
    for i, (titre, octets) in enumerate(lignes, 1):
        con.execute("INSERT INTO fragments (titre, octets) VALUES (?,?)", (titre, octets))
        con.execute("INSERT INTO fragments_fts (rowid, titre) VALUES (?,?)", (i, titre))
    con.commit()
    con.close()
    return src


def _tables_ordinaire(con) -> list[str]:
    """Tables ordinaires SEULEMENT : les shadow tables FTS sont reconstruites, pas comparees."""
    virtuelles = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE 'CREATE VIRTUAL TABLE%'")]
    tous = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return [t for t in tous if t not in virtuelles
            and not any(t.startswith(v + "_") for v in virtuelles)]


def _contenu_ordinaire(db: Path) -> dict:
    con = sqlite3.connect(db)
    try:
        return {t: con.execute('SELECT rowid, * FROM "%s" ORDER BY rowid' % t).fetchall()
                for t in _tables_ordinaire(con)}
    finally:
        con.close()


def _alterer_une_part(mod, archive: Path, dest: Path, cle: str) -> str:
    """Reecrit l'archive en changeant UN octet d'une part donnees, manifeste INTACT.

    Le verificateur ne doit accuser que l'ecart d'empreinte : si la part fausse passe,
    c'est que la comparaison sha256 du manifeste ne se fait pas. La relecture des membres
    passe par `_fabrique` (le meme chemin que `archive-verifier`) -- un capteur casse serait
    deja tombe au aller-retour, qui mesure le vrai stockage.
    """
    import py7zr
    blocs: dict[str, bytearray] = {}

    class _Capture:
        def morceau(self, nom, b):
            blocs.setdefault(nom, bytearray()).extend(b)

        def fin(self, nom, emp):
            pass

    with py7zr.SevenZipFile(archive, "r", password=cle) as z:
        z.extract(factory=mod._fabrique(_Capture()))
    donnees = sorted(n for n in blocs if n.startswith("donnees/"))
    if not donnees:
        return ""
    cible = donnees[0]
    octets = bytes(blocs[cible])
    i = len(octets) // 2
    altere = octets[:i] + bytes([octets[i] ^ 0xFF]) + octets[i + 1:]   # meme longueur
    filtres = [{"id": py7zr.FILTER_COPY}, {"id": py7zr.FILTER_CRYPTO_AES256_SHA256}]
    with py7zr.SevenZipFile(dest, "w", password=cle, header_encryption=True, filters=filtres) as z:
        for nom in blocs:    # ordre indifferent : le verificateur lit le manifeste
            z.writestr(altere if nom == cible else bytes(blocs[nom]), nom)
    return cible


def test_les_trois_sous_commandes_font_un_aller_retour_identique(mod, monkeypatch, tmp_path):
    src = _base(tmp_path)
    avant = _contenu_ordinaire(src)
    arc = tmp_path / "archives" / "flux.7z"

    assert _lance(mod, monkeypatch, "archive-flux",
                  "--source", str(src), "--cible", str(arc)) == 0, \
        "archive-flux n'a pas rendu 0"
    assert arc.exists(), "archive-flux n'a pas ecrit l'archive chiffree"

    assert _lance(mod, monkeypatch, "archive-verifier",
                  "--archive", str(arc)) == 0, "archive-verifier refuse une archive neuve"

    dest = tmp_path / "restaure.db"
    assert not dest.exists()
    assert _lance(mod, monkeypatch, "archive-restaurer",
                  "--archive", str(arc), "--dest", str(dest)) == 0, \
        "archive-restaurer n'a pas rendu 0"
    assert dest.exists(), "archive-restaurer n'a pas ecrit la base restauree"

    assert _contenu_ordinaire(dest) == avant, \
        "le contenu ordinaire (BLOB compris) ne revient pas octet pour octet"

    con = sqlite3.connect(dest)
    try:
        hit = con.execute(
            "SELECT COUNT(*) FROM fragments_fts WHERE fragments_fts MATCH 'revocation'"
        ).fetchone()[0]
    finally:
        con.close()
    assert hit == 1, "le FTS reconstruit a la restauration ne repond pas au MATCH"


def test_une_archive_alteree_est_refusee_par_archive_verifier(mod, monkeypatch, tmp_path):
    src = _base(tmp_path)
    arc = tmp_path / "flux.7z"
    assert _lance(mod, monkeypatch, "archive-flux",
                  "--source", str(src), "--cible", str(arc)) == 0

    alteree = tmp_path / "alteree.7z"
    part = _alterer_une_part(mod, arc, alteree, CLE_DE_TEST)
    assert part, "aucune part donnees dans l'archive : rien a alterer, rien mesure"

    rc = _lance(mod, monkeypatch, "archive-verifier", "--archive", str(alteree))
    assert rc != 0, (
        "archive-verifier a ACCEPTE une archive dont la part %s a ete alteree (rc=0)" % part)


def test_archive_restaurer_refuse_une_destination_existante(mod, monkeypatch, tmp_path):
    src = _base(tmp_path)
    arc = tmp_path / "flux.7z"
    assert _lance(mod, monkeypatch, "archive-flux",
                  "--source", str(src), "--cible", str(arc)) == 0

    dest = tmp_path / "deja_la.db"
    dest.write_text("ne me ecrase pas", encoding="utf-8")
    with pytest.raises(SystemExit, match="destination EXISTANTE"):
        _lance(mod, monkeypatch, "archive-restaurer",
               "--archive", str(arc), "--dest", str(dest))
    assert dest.read_text(encoding="utf-8") == "ne me ecrase pas", \
        "la destination existante a ete modifiee malgre le refus"


# ---------------------------------------------------------------------------
# Defaut #4 (relecture 47eb607af) : FTS alimentee par un TRIGGER
# ---------------------------------------------------------------------------

def _base_avec_declencheur(tmp_path: Path) -> Path:
    """Table ordinaire dont un trigger AFTER INSERT remplit une table FTS5.

    C'est la topologie d'embeddings.db : le schema (trigger compris) ne doit PAS
    etre applique avant les donnees -- sinon le trigger indexe chaque ligne au
    moment de son insertion PUIS le contenu archive de la FTS est reinsere.
    """
    src = tmp_path / "declencheur.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, txt TEXT)")
    con.execute("CREATE VIRTUAL TABLE f USING fts5(txt)")
    con.execute(
        "CREATE TRIGGER t_vers_f AFTER INSERT ON t "
        "BEGIN INSERT INTO f(rowid, txt) VALUES (new.id, new.txt); END")
    for i, txt in enumerate(("memoire organisme", "revocation cle", "archive en flux"), 1):
        con.execute("INSERT INTO t (id, txt) VALUES (?,?)", (i, txt))
    con.commit()
    con.close()
    return src


def test_restaurer_ne_double_indexe_pas_le_fts_alimente_par_declencheur(mod, monkeypatch, tmp_path):
    src = _base_avec_declencheur(tmp_path)
    arc = tmp_path / "flux_declencheur.7z"
    assert _lance(mod, monkeypatch, "archive-flux",
                  "--source", str(src), "--cible", str(arc)) == 0, \
        "archive-flux n'a pas archive la base a trigger"

    dest = tmp_path / "restaure_declencheur.db"
    assert _lance(mod, monkeypatch, "archive-restaurer",
                  "--archive", str(arc), "--dest", str(dest)) == 0, \
        "archive-restaurer n'a pas rendu 0"

    con = sqlite3.connect(dest)
    try:
        total = con.execute("SELECT COUNT(*) FROM f").fetchone()[0]
        for terme in ("memoire", "revocation", "archive"):
            hits = con.execute(
                "SELECT COUNT(*) FROM f WHERE f MATCH ?", (terme,)).fetchone()[0]
            assert hits == 1, (
                "MATCH '%s' rend %d lignes (attendu 1) : la restauration a reinsere le "
                "contenu archive de f EN PLUS de ce que le trigger a indexe" % (terme, hits))
    finally:
        con.close()
    assert total == 3, (
        "f contient %d lignes apres restauration (attendu 3) : le schema complet, "
        "trigger compris, a ete applique avant les donnees => chaque ligne indexee "
        "deux fois" % total)


# ---------------------------------------------------------------------------
# Defaut #5 (relecture 47eb607af) : tables WITHOUT ROWID
# ---------------------------------------------------------------------------

def _base_sans_rowid(tmp_path: Path) -> Path:
    """Table WITHOUT ROWID : `SELECT rowid, *` y est une erreur SQL."""
    src = tmp_path / "sans_rowid.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE w(k TEXT PRIMARY KEY, v BLOB) WITHOUT ROWID")
    for k, v in (("alpha", b"\x00\x01\xff"), ("beta", None), ("gamma", bytes(range(16)))):
        con.execute("INSERT INTO w (k, v) VALUES (?,?)", (k, v))
    con.commit()
    con.close()
    return src


def _contenu_w(db: Path) -> list:
    con = sqlite3.connect(db)
    try:
        return con.execute('SELECT k, v FROM w ORDER BY k').fetchall()
    finally:
        con.close()


def test_table_without_rowid_fait_un_aller_retour(mod, monkeypatch, tmp_path):
    src = _base_sans_rowid(tmp_path)
    avant = _contenu_w(src)
    arc = tmp_path / "sans_rowid.7z"

    assert _lance(mod, monkeypatch, "archive-flux",
                  "--source", str(src), "--cible", str(arc)) == 0, \
        "archive-flux a plante ou a refuse une table WITHOUT ROWID (SELECT rowid, * ?)"

    dest = tmp_path / "restaure_sans_rowid.db"
    assert _lance(mod, monkeypatch, "archive-restaurer",
                  "--archive", str(arc), "--dest", str(dest)) == 0, \
        "archive-restaurer n'a pas rendu 0 sur une base WITHOUT ROWID"

    assert _contenu_w(dest) == avant, \
        "le contenu de la table WITHOUT ROWID ne revient pas octet pour octet"


# ---------------------------------------------------------------------------
# Defaut #6 (relecture 47eb607af) : hack de chargement en production
# ---------------------------------------------------------------------------

def test_aucun_hack_de_chargement_dans_le_module():
    source = (ROOT / "tools" / "forge_backup_hotswap.py").read_text(encoding="utf-8")
    assert "import types as _types_amorce" not in source, (
        "le module s'amorce encore lui-meme via `import types as _types_amorce` : "
        "c'est au chargeur (voir _charger_le_module) d'enregistrer le module, pas au code")
    assert "_sys_amorce.modules.setdefault" not in source, (
        "le module s'inscrit encore dans sys.modules en production "
        "(`_sys_amorce.modules.setdefault`) : hack a retirer")
