"""
tools/forge_gitingest_sdk_ingest.py — Ingest gitingest SDK dumps into Nokido RAG.
Reads docs/gitingest_*.txt, chunks, writes NEW chunks into rag_chunks domain=sdk_gitingest
(an id already present is skipped BEFORE any insert -- see ingest_file).
"""

import glob
import hashlib
import re
import sqlite3
import time
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = LAFORGE_ROOT / "RAG" / "embeddings.db"
SEPARATOR = "=" * 80
CHUNK_SIZE = 800
OVERLAP = 100


def _chunks(text: str, size: int = CHUNK_SIZE, overlap: int = OVERLAP):
    start = 0
    while start < len(text):
        yield text[start : start + size]
        start += size - overlap
        if start >= len(text):
            break


def _source_de_section(lines: list[str], path: Path, idx: int) -> tuple[str, str]:
    """Nom de fichier REEL d'une section, et son code.

    La premiere ligne d'une section n'est un chemin que si le dump en contient un.
    Prise aveuglement, elle capture les en-tetes du format gitingest lui-meme :
    mesure 24-07, ~11.6k chunks portaient « Directory structure: »,
    « # SECTION: app/ (559 files) » ou « ==== » comme SOURCE. Une source qui est en
    fait du contenu ne dit plus qui parle, et le RAG ne peut plus pondérer ce qu'il
    rend. Mieux vaut une source synthetique honnete qu'un fragment de prose.
    """
    tete = lines[0].strip()
    reste = "\n".join(lines[1:]).strip()

    # Forme explicite du dump : « FILE: chemin/vers/x.py »
    for prefixe in ("FILE:", "File:", "file:"):
        if tete.startswith(prefixe):
            candidat = tete[len(prefixe):].strip()
            if candidat:
                return candidat, reste

    # Chemin plausible : pas d'espace, et une extension courte en fin
    base = tete.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    ext = base.rsplit(".", 1)[-1] if "." in base else ""
    if tete and " " not in tete and 0 < len(ext) <= 5 and ext.isalnum():
        return tete, reste

    # Sinon la tete EST du contenu : ne pas la promouvoir en source, et surtout
    # ne pas la perdre — elle repart dans le corps indexe.
    return f"{path.name}#section{idx}", "\n".join(lines).strip()


# Format gitingest REEL (mesure 24-07) : chaque fichier est un bloc
#   <ligne de '='>            (longueur VARIABLE : 48 le plus souvent, pas 80)
#   FILE: chemin/vers/x.py
#   <ligne de '='>
#   <contenu jusqu'au bloc suivant>
# L'ancien `content.split(SEPARATOR)` avec SEPARATOR = 80 '=' ne matchait JAMAIS
# (les vraies lignes font 48) : tout le dump restait une seule section, `lines[0]`
# valait « Directory structure: » -> 24k chunks a source degradee. On lit desormais
# le marqueur FILE: directement, qui porte le vrai chemin. Longueur du separateur
# toleree des 20 '=' pour survivre a une regeneration au format legerement different.
_BLOC_RE = re.compile(r"^={20,}\r?\nFILE:\s*(?P<path>.+?)\r?\n={20,}\r?\n", re.M)


def _blocs_fichiers(content: str, path: Path):
    """Rend (chemin, contenu) pour chaque fichier du dump — DEUX formats coexistent.

    Format A (recent, laforge/tools/ctf/docs) : bloc « ===\\nFILE: chemin\\n=== ».
    Format B (ancien, veille_*) : « chemin » en tete de section, sections separees
    par une ligne de 80 '='. Mesure 24-07 : parser A seul PERDAIT les 7 dumps veille
    (1078 chunks gemini). On tente A ; a defaut de marqueur FILE:, on retombe sur B.
    """
    marques = list(_BLOC_RE.finditer(content))
    if marques:  # format A
        for i, m in enumerate(marques):
            deb = m.end()
            fin = marques[i + 1].start() if i + 1 < len(marques) else len(content)
            yield m.group("path").strip(), content[deb:fin].strip()
        return
    # format B : section = tete (chemin) + corps, separateur = 80 '='
    for idx, section in enumerate(content.split(SEPARATOR)):
        lines = section.strip().splitlines()
        if not lines:
            continue
        src, code = _source_de_section(lines, path, idx)
        if code:
            yield src, code


def _est_ligne_egale(ligne: str) -> bool:
    """Ligne de >= 20 '=' TERMINEE par un saut de ligne (comme `_BLOC_RE`)."""
    return ligne.endswith("\n") and len(ligne.rstrip("\r\n")) >= 20 \
        and set(ligne.rstrip("\r\n")) == {"="}


def _chemin_file(ligne: str):
    m = re.match(r"FILE:\s*(?P<path>.+?)\r?\n\Z", ligne)
    return m.group("path").strip() if m else None


def _marqueur(fenetre: list):
    """Chemin si les 3 lignes forment un marqueur de format A, sinon None."""
    if _est_ligne_egale(fenetre[0]) and _est_ligne_egale(fenetre[2]):
        return _chemin_file(fenetre[1])
    return None


def _format_a(path: Path) -> bool:
    with open(path, encoding="utf-8", errors="replace") as f:
        fenetre = []
        for ligne in f:
            fenetre = (fenetre + [ligne])[-3:]
            if len(fenetre) == 3 and _marqueur(fenetre) is not None:
                return True
    return False


def _blocs_fichiers_flux(path: Path):
    """`_blocs_fichiers` EN FLUX : memes blocs, memoire bornee par le bloc.

    Mesure 2026-09-23 : `read_text` + `list(blocs)` sur des dumps de 950 Mo a fait
    tuer l'ingestion a 7 138 Mo de RSS. Equivalence prouvee par NR contre
    `_blocs_fichiers` (formats A et B, separateur colle dans une ligne, sections
    vides, fin sans saut de ligne).
    """
    if _format_a(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            courant, corps, pend = None, [], []
            for ligne in f:
                pend.append(ligne)
                if len(pend) < 3:
                    continue
                chemin = _marqueur(pend)
                if chemin is not None:
                    if courant is not None:
                        yield courant, "".join(corps).strip()
                    courant, corps, pend = chemin, [], []
                else:
                    if courant is not None:
                        corps.append(pend[0])
                    pend.pop(0)
            if courant is not None:
                yield courant, "".join(corps + pend).strip()
        return

    def _emettre(section: str, idx: int):
        lines = section.strip().splitlines()
        if lines:
            src, code = _source_de_section(lines, path, idx)
            if code:
                yield src, code

    with open(path, encoding="utf-8", errors="replace") as f:
        idx, sect = 0, []
        for ligne in f:
            morceaux = ligne.split(SEPARATOR)
            sect.append(morceaux[0])
            for m in morceaux[1:]:
                yield from _emettre("".join(sect), idx)
                idx, sect = idx + 1, [m]
        yield from _emettre("".join(sect), idx)


def ingest_file(path: Path, conn: sqlite3.Connection, pendant=None,
                tous_les: int = 20000) -> tuple[int, int]:
    """`pendant()` (optionnel) est appele tous les `tous_les` chunks INSERES.

    Mesure 2026-09-23 : un seul dump de ~950 Mo a fait passer V: de 53 a 4 Go
    libres PENDANT son ingestion — le garde disque et le rendu du WAL de
    l'appelant n'agissaient qu'entre deux dumps. `pendant` peut lever pour
    arreter proprement (les chunks deja inseres restent : INSERT OR IGNORE).
    """
    inserted = skipped = 0
    # EN FLUX : ni `read_text` du dump entier, ni `list(blocs)` (job tue a 7 Go).
    blocs = _blocs_fichiers_flux(path)
    for filename, code in tqdm(blocs, desc=path.name, unit="file", leave=False):
        if not code:
            continue

        for chunk in _chunks(code):
            chunk = chunk.strip()
            if not chunk:
                continue
            source = filename or path.name
            chunk_id = hashlib.sha256((source + chunk).encode()).hexdigest()[:16]
            # DEJA PRESENT -> rien a ecrire (2026-10-01). Le trigger `rag_chunks_fts_bi`
            # (BEFORE INSERT) retirait l'entree lexicale de l'id existant AVANT que
            # l'INSERT OR IGNORE soit ignore : chaque re-ingestion d'un depot sortait ses
            # chunks inchanges de `rag_chunks_fts` (echantillon 1/500 : 38 % des chunks
            # de septembre absents, 40/40 sources touchees re-ingerees). existence-verifiee
            if conn.execute("SELECT 1 FROM rag_chunks WHERE id = ?", (chunk_id,)).fetchone():
                skipped += 1
                continue
            conn.execute(
                "INSERT OR IGNORE INTO rag_chunks (id, source, text, domain, created_at) "
                "VALUES (?, ?, ?, 'sdk_gitingest', ?)",
                (chunk_id, source, chunk, int(time.time())),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
                if pendant is not None and inserted % tous_les == 0:
                    pendant()
                # Sync rag_fts pour recherche BM25 immédiate (sinon le chunk reste
                # invisible tant que l'embedding NPU n'est pas calculé). Pattern =
                # anchor_solution (forge_self_correction). FTS5 standalone.
                try:
                    conn.execute(
                        "INSERT INTO rag_fts (chunk_id, text, source, domain) "
                        "VALUES (?, ?, ?, 'sdk_gitingest')",
                        (chunk_id, chunk, source),
                    )
                except Exception:
                    pass
            else:
                skipped += 1

    conn.commit()
    return inserted, skipped


def main():
    pattern = str(LAFORGE_ROOT / "docs" / "gitingest_*.txt")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No files matching: {pattern}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    # Ensure created_at column exists
    try:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN created_at INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    total_inserted = total_skipped = 0
    for fp in tqdm(files, desc="gitingest files", unit="file"):
        ins, skip = ingest_file(Path(fp), conn)
        total_inserted += ins
        total_skipped += skip
        print(f"  {Path(fp).name}: +{ins} chunks ({skip} skipped)")

    conn.close()
    print(f"\nTotal: {total_inserted} inserted, {total_skipped} skipped")
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    main()
