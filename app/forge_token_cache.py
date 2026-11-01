"""
app/forge_token_cache.py - Cache partagé dédié à l'économie de tokens client (MCP / RFC 9110)

Pourquoi l'existant ne convient pas :
- forge_prompt_cache.py gère le caching de préfixes côté API LLM (Anthropic ephemeral / Gemini prompt caching),
  sans lien avec le transport MCP ni la lecture conditionnelle de fichiers.
- Aucun module existant ne supporte l'ETag de contenu ni la lecture conditionnelle (RFC 9110)
  pour éviter de renvoyer le contenu intégral aux clients MCP ayant déjà la version courante.
- Un cache de session côté serveur pur échoue si le client a compacté son contexte : seul le client
  connaît l'ETag qu'il détient encore dans sa mémoire active.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

__FORGE_COLOR__ = "memoire/cache_lecture"

MAX_VERSIONS = 5
MAX_FILE_SIZE = 512 * 1024  # 512 Ko


def _get_base_dir() -> Path:
    override = os.environ.get("LAFORGE_TOKEN_CACHE_DIR")
    if override:
        return Path(override)
    return Path("sandbox") / "token_cache"


def etag(contenu: str) -> str:
    """Calcule l'empreinte ETag (sha256 hex[:16]) d'un contenu textuel."""
    return hashlib.sha256(contenu.encode("utf-8")).hexdigest()[:16]


def _calculer_cle_fichier(racine: str, chemin_abs: str) -> str:
    cle_brute = f"{racine}|{chemin_abs}"
    return hashlib.sha256(cle_brute.encode("utf-8")).hexdigest()[:16]


def _chemin_relatif(racine: str, chemin_abs: str) -> str:
    try:
        rel = os.path.relpath(chemin_abs, racine)
        return rel.replace("\\", "/")
    except Exception:
        return chemin_abs.replace("\\", "/")


def _gerer_instantanes(dossier_cle: Path, etag_actuel: str, contenu: str) -> None:
    """
    Sauvegarde l'instantané sous dossier_cle/<etag>.txt si contenu <= 512 Ko,
    et purge pour conserver 5 versions max (la plus ancienne en mtime est retirée).
    """
    if len(contenu.encode("utf-8")) > MAX_FILE_SIZE:
        return

    dossier_cle.mkdir(parents=True, exist_ok=True)
    fichier_inst = dossier_cle / f"{etag_actuel}.txt"

    if fichier_inst.is_file():
        # Déjà présent, mettre à jour le mtime pour le considérer récent
        try:
            now = time.time()
            os.utime(fichier_inst, (now, now))
        except OSError:
            pass
    else:
        fichier_inst.write_text(contenu, encoding="utf-8")

    # Vérification et purge des versions excédentaires (> MAX_VERSIONS)
    fichiers = list(dossier_cle.glob("*.txt"))
    if len(fichiers) > MAX_VERSIONS:
        fichiers.sort(key=lambda p: (p.stat().st_mtime, p.name))
        while len(fichiers) > MAX_VERSIONS:
            a_supprimer = fichiers.pop(0)
            try:
                a_supprimer.unlink()
            except OSError:
                pass


def _lire_instantane(dossier_cle: Path, tag: str) -> Optional[str]:
    fichier = dossier_cle / f"{tag}.txt"
    if fichier.is_file():
        try:
            return fichier.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _journaliser_economie(base_dir: Path, rel_path: str, mode: str, tokens_evites: int) -> None:
    if tokens_evites <= 0:
        return
    base_dir.mkdir(parents=True, exist_ok=True)
    fichier_journal = base_dir / "token_savings.jsonl"
    entree = {
        "horodatage": time.time(),
        "chemin": rel_path,
        "mode": mode,
        "tokens_evites": tokens_evites,
    }
    try:
        with fichier_journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except OSError:
        pass


def bilan_economie(fenetre_s: int = 86400, maintenant: Optional[float] = None, base_dir=None,
                   lignes_max: int = 5000, octets_max: int = 2_000_000) -> dict:
    """Economie des lectures conditionnelles sur `fenetre_s`, lue dans `token_savings.jsonl` (cle `tokens_evites`).

    Symbiose (owner 31/10) : section `economie_etag` de forge_stats. Le journal n'est ecrit QUE quand des tokens sont
    evites (`_journaliser_economie`) : `appels` compte les lectures economes, pas un taux de reussite. Journal absent
    = ILLISIBLE, jamais 0 (un compteur muet lu « 0 token evite » serait un faux calme). La BORNE DIT COMBIEN.
    """
    now = time.time() if maintenant is None else maintenant
    chemin = Path(base_dir or _get_base_dir()) / "token_savings.jsonl"
    try:
        taille = chemin.stat().st_size
    except OSError:
        return {"etat": "ILLISIBLE", "raison": "journal absent : %s" % chemin.name}
    with chemin.open("rb") as f:
        if taille > octets_max:
            f.seek(taille - octets_max)
        texte = f.read().decode("utf-8", "replace")
    if taille > octets_max:
        texte = texte.partition("\n")[2]   # premiere ligne coupee : jetee, jamais lue comme complete
    par_mode: Dict[str, Dict[str, int]] = {}
    chemins: Dict[str, int] = {}
    illisibles = 0
    for ligne in texte.splitlines()[-lignes_max:]:
        try:
            e = json.loads(ligne)
            age = now - float(e.get("horodatage") or 0)
        except (ValueError, TypeError, AttributeError):
            illisibles += 1          # COMPTEE, jamais tue
            continue
        if age > fenetre_s:
            continue
        m = par_mode.setdefault(str(e.get("mode") or "?"), {"appels": 0, "tokens_evites": 0})
        m["appels"] += 1
        m["tokens_evites"] += int(e.get("tokens_evites") or 0)
        c = str(e.get("chemin") or "?")
        chemins[c] = chemins.get(c, 0) + int(e.get("tokens_evites") or 0)
    top = sorted(chemins.items(), key=lambda kv: -kv[1])[:5]
    return {"etat": "MESURE", "fenetre_s": fenetre_s, "par_mode": par_mode,
            "tokens_evites": sum(m["tokens_evites"] for m in par_mode.values()),
            "fichiers_les_plus_economes": [{"chemin": c, "tokens_evites": t} for c, t in top],
            "lignes_illisibles": illisibles,
            "borne": "%d lignes / %d octets depuis la fin" % (lignes_max, octets_max)}


def lecture_conditionnelle(
    chemin_abs: str,
    contenu: str,
    racine: str,
    si_etag: Optional[str] = None,
    depuis_etag: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Effectue une lecture conditionnelle RFC 9110 (ETag / If-None-Match).

    Args:
        chemin_abs: Chemin absolu du fichier lu.
        contenu: Contenu textuel actuel du fichier sur disque.
        racine: Racine canonique du worktree appelant (isolation stricte).
        si_etag: ETag que le client possède pour ce fichier (If-None-Match).
        depuis_etag: ETag de référence à partir duquel calculer un diff unifié.

    Returns:
        dict: {
            "mode": "PLEIN" | "INCHANGE" | "DIFF",
            "etag": str,
            "corps": str,
            "tokens_evites": int
        }
    """
    etag_courant = etag(contenu)
    base_dir = _get_base_dir()
    cle_fic = _calculer_cle_fichier(racine, chemin_abs)
    dossier_cle = base_dir / cle_fic

    # Enregistrement ou mise à jour de l'instantané pour les futures comparaisons
    _gerer_instantanes(dossier_cle, etag_courant, contenu)

    taille_tokens_estimee = len(contenu) // 4
    rel_path = _chemin_relatif(racine, chemin_abs)

    # 1. Cas si_etag == etag courant -> INCHANGE (Zero-Reload)
    if si_etag is not None and si_etag == etag_courant:
        corps = f"[INCHANGE etag={etag_courant}]"
        tokens_evites = max(0, taille_tokens_estimee - (len(corps) // 4))
        _journaliser_economie(base_dir, rel_path, "INCHANGE", tokens_evites)
        return {
            "mode": "INCHANGE",
            "etag": etag_courant,
            "corps": corps,
            "tokens_evites": tokens_evites,
        }

    # 2. Cas depuis_etag fourni et présent dans les instantanés -> tentative DIFF
    if depuis_etag is not None and depuis_etag != etag_courant:
        ancien_contenu = _lire_instantane(dossier_cle, depuis_etag)
        if ancien_contenu is not None:
            lignes_anc = ancien_contenu.splitlines(keepends=True)
            lignes_cur = contenu.splitlines(keepends=True)
            diff_lignes = list(
                difflib.unified_diff(
                    lignes_anc,
                    lignes_cur,
                    fromfile=f"{rel_path} (etag:{depuis_etag})",
                    tofile=f"{rel_path} (etag:{etag_courant})",
                )
            )
            diff_texte = "".join(diff_lignes)

            # Si le diff ne dépasse pas 50 % de la taille du contenu
            if len(diff_texte) <= 0.5 * len(contenu):
                tokens_evites = max(0, taille_tokens_estimee - (len(diff_texte) // 4))
                _journaliser_economie(base_dir, rel_path, "DIFF", tokens_evites)
                return {
                    "mode": "DIFF",
                    "etag": etag_courant,
                    "corps": diff_texte,
                    "tokens_evites": tokens_evites,
                }

    # 3. Mode PLEIN par défaut (opt-in strict si ni si_etag ni depuis_etag, ou diff > 50%, ou etag inconnu)
    return {
        "mode": "PLEIN",
        "etag": etag_courant,
        "corps": contenu,
        "tokens_evites": 0,
    }
