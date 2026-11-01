"""forge_bench_traduction -- banc MESURE de la traduction FR->EN pour economiser des tokens (GO owner 2026-10-28).

100 % local, 0 token cloud. Dependances (ctranslate2, sentencepiece, tiktoken, psutil) dans un venv ISOLE
sandbox/workspace/trad_env, modeles opus-mt fr-en / en-fr convertis CTranslate2 int8 sous sandbox/workspace/models/.
    python tools/forge_bench_traduction.py --setup      (cree le venv, installe, convertit ; en ligne)
    <trad_env>/Scripts/python.exe tools/forge_bench_traduction.py   (mesure ; rapport JSON + docs/mesures/*.md)
Dependance absente => statut ILLISIBLE dit, jamais un gain invente. o200k_base / cl100k_base sont des
APPROXIMATIONS : le tokenizer Claude n'est pas public. Jamais %NOKIDO_DATA%\embeddings.db.
"""
from __future__ import annotations

__FORGE_COLOR__ = "mesure/banc_traduction : mesure reelle du gain de tokens FR->EN, preservation des identifiants, qualite"

import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return RACINE
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
WORK = _RACINE_DONNEES / "sandbox" / "workspace"
VENV = WORK / "trad_env"
MODELES = WORK / "models"
PROJETS = Path.home() / ".claude" / "projects" / "C--Users-user-Script-python-IA"
ENCODAGES = ("o200k_base", "cl100k_base")
# Recette owner 28/10 : la mesure « n'avancait pas » -- les 3 volets parcouraient TOUTES les conversations Claude Code
# (centaines de Mo), sans progression. Le corpus n'en demande que quelques dizaines d'extraits.
MAX_CONVERSATIONS = 5
TERMES = ["UNKNOWN", "NO", "STALE", "DEAD", "REQUESTED", "ACCEPTED", "ACHIEVED", "ILLISIBLE", "palier", "organe"]

_MOTIF = re.compile(
    r"```.*?```"                                  # blocs de code
    r"|`[^`\n]+`"                                 # code inline
    r"|mcp__[A-Za-z0-9_]+"                        # outils MCP
    r"|[A-Za-z]:[\\/][^\s`\"',;)]*"               # chemins Windows
    r"|(?<![\w/])(?:[\w.-]+/)+[\w.-]+"            # chemins relatifs
    r"|(?<![\w-])--?[A-Za-z][\w-]*(?:=[^\s]+)?(?=[\s.,;)]|$)"  # flags CLI
    r"|\bjob_[A-Za-z0-9]+"                        # job_id
    r"|\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b",        # sha
    re.S,
)


def masquer(texte: str):
    """Remplace chaque identifiant par XQ<n>X ; rend (texte masque, {placeholder: original})."""
    table: dict = {}

    def _m(m):
        cle = f"XQ{len(table)}X"
        table[cle] = m.group(0)
        return cle

    return _MOTIF.sub(_m, texte), table


def restaurer(texte: str, table: dict) -> str:
    for cle in sorted(table, key=len, reverse=True):
        texte = texte.replace(cle, table[cle])
    return texte


def taux_intacts(traduit: str, table: dict):
    """(identifiants dont le placeholder survit exactement une fois, total)."""
    ok = sum(1 for cle in table if len(re.findall(rf"\b{cle}\b", traduit)) == 1)
    return ok, len(table)


def compter(texte: str, encodage: str):
    """Nombre de tokens tiktoken, ou None (ILLISIBLE) si tiktoken/encodage indisponible."""
    try:
        import tiktoken

        return len(tiktoken.get_encoding(encodage).encode(texte))
    except Exception:
        return None


def termes_preserves(traduit: str, termes) -> dict:
    return {t: bool(re.search(rf"\b{re.escape(t)}\b", traduit)) for t in termes}


# ---------------------------------------------------------------- corpus (reel, lecture seule)
def _textes_jsonl():
    """Objets des MAX_CONVERSATIONS conversations les plus RECENTES (jamais toutes), progression sur stderr."""
    try:
        fichiers = sorted(PROJETS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_CONVERSATIONS]
    except OSError:
        fichiers = []
    for k, f in enumerate(fichiers, 1):
        print(f"[corpus] conversation {k}/{len(fichiers)} : {f.name}", file=sys.stderr, flush=True)
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                for ligne in fh:
                    try:
                        yield json.loads(ligne)
                    except ValueError:  # muet-ok : ligne JSONL corrompue, une seule ligne ecartee
                        continue
        except OSError as exc:
            # Un fichier ILLISIBLE (compte du hub sans acces au profil owner) se DIT : sinon le volet 1 serait
            # mesure sur un corpus vide ou partiel sans que le rapport le sache.
            import logging
            logging.getLogger(__name__).warning("conversation illisible %s (%s) : volet 1 incomplet",
                                                f.name, type(exc).__name__)
            continue


def _texte_user(o):
    if o.get("type") != "user":
        return None
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list) and c and all(isinstance(x, dict) and x.get("type") == "text" for x in c):
        return "\n".join(x.get("text", "") for x in c)
    return None


def _echantillon(liste, n):
    if len(liste) <= n:
        return liste
    pas = len(liste) / n
    return [liste[int(i * pas)] for i in range(n)]


def corpus_volet1(n=20):
    cand = []
    for o in _textes_jsonl():
        t = _texte_user(o)
        if t and 60 <= len(t) <= 1500 and "```" not in t and not t.lstrip().startswith("<") and t.count("\n") < 12:
            cand.append(t.strip())
    return _echantillon(cand, n)


def corpus_volet2():
    docs = [RACINE / "CLAUDE.md", RACINE / "Nokido" / "CLAUDE.md", RACINE / "Nokido" / "RULES_SHARED.md",
            Path.home() / ".claude" / "projects" / "C--Users-user-Script-python-IA" / "memory" / "MEMORY.md"]
    out = [(str(p.name), p.read_text(encoding="utf-8", errors="replace")) for p in docs if p.is_file()]
    hooks = []
    for o in _textes_jsonl():
        s = json.dumps(o, ensure_ascii=False)
        if "hook" in s.lower() and "additionalContext" in s or "system-reminder" in s and "hook" in s.lower():
            att = o.get("attachment") or {}
            t = att.get("content") or att.get("stdout") or ""
            if isinstance(t, str) and 80 <= len(t) <= 3000:
                hooks.append(t)
    out += [(f"hook_{i}", t) for i, t in enumerate(_echantillon(hooks, 5))]
    return out


def corpus_volet3():
    taches = []
    db = _RACINE_DONNEES / "sandbox" / "tasks.db"
    if db.is_file():
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            taches = [r[0] for r in con.execute(
                "SELECT description FROM tasks WHERE length(description) BETWEEN 80 AND 3000 ORDER BY rowid DESC LIMIT 200")]
        finally:
            con.close()
    sorties = []
    for o in _textes_jsonl():
        c = (o.get("message") or {}).get("content")
        if o.get("type") == "user" and isinstance(c, list):
            for x in c:
                if isinstance(x, dict) and x.get("type") == "tool_result" and isinstance(x.get("content"), str):
                    if 80 <= len(x["content"]) <= 3000 and x["content"].lstrip().startswith("{"):
                        sorties.append(x["content"])
    return _echantillon(taches, 10), _echantillon(sorties, 10)


# ---------------------------------------------------------------- traduction
class Traducteur:
    def __init__(self, sens: str):
        import ctranslate2
        import sentencepiece as spm

        d = MODELES / sens
        self.tr = ctranslate2.Translator(str(d), device="cpu", compute_type="int8")
        self.src = spm.SentencePieceProcessor(model_file=str(d / "source.spm"))
        self.tgt = spm.SentencePieceProcessor(model_file=str(d / "target.spm"))

    LOT = 16
    MAX_ENTREE = 250       # tokens par morceau : MarianMT n'a que 512 positions (recette 28/10, 3e passage)
    MAX_DECODAGE = 500

    def __call__(self, texte: str) -> str:
        """Lignes traduites par morceaux de MAX_ENTREE tokens, lots de 16, decodage BORNE (2x + 16, plafond 500),
        beam 1. Recette owner 28/10 : un lot unique, beam 2 et 512 fixes bouclaient ; puis « No position encodings
        for positions >= 512 » sur une ligne longue du volet 2."""
        lignes = texte.split("\n")
        morceaux = []  # (indice de ligne, tokens)
        for i, l in enumerate(lignes):
            if l.strip():
                toks = self.src.encode(l, out_type=str)
                pas = self.MAX_ENTREE - 1  # place du `</s>` : la limite porte sur l'entree REELLE du modele
                for d in range(0, len(toks), pas):
                    # `</s>` OBLIGATOIRE en fin d'entree MarianMT (recette 28/10, 4e passage : sans lui le decodeur
                    # ne s'arrete qu'au plafond -- sorties en boucle, gain mesure -233 %)
                    morceaux.append((i, toks[d:d + pas] + ["</s>"]))
        sorties: dict = {}
        for d in range(0, len(morceaux), self.LOT):
            part = morceaux[d:d + self.LOT]
            lots = [m[1] for m in part]
            borne = min(self.MAX_DECODAGE, 2 * max(len(l) - 1 for l in lots) + 16)  # contenu, hors `</s>`
            res = self.tr.translate_batch(lots, beam_size=1, max_decoding_length=borne,
                                          repetition_penalty=1.2, no_repeat_ngram_size=4)
            for (i, _), r in zip(part, res):
                hyp = [tok for tok in r.hypotheses[0] if tok != "</s>"]
                sorties.setdefault(i, []).append(self.tgt.decode(hyp))
        for i, morceaux_traduits in sorties.items():
            lignes[i] = " ".join(morceaux_traduits)
        return "\n".join(lignes)


def _ram_mo():
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return None


def mesurer_volet(nom, textes, fr_en, en_fr):
    lignes, intacts, total, lat, echant = [], 0, 0, 0.0, []
    tok = {e: [0, 0] for e in ENCODAGES}
    termes = {t: [0, 0] for t in TERMES}
    for k_texte, t in enumerate(textes, 1):
        print(f"[mesure] {nom} {k_texte}/{len(textes)} ({len(t)} car.)", file=sys.stderr, flush=True)
        masque, table = masquer(t)
        t0 = time.perf_counter()
        en = fr_en(masque)
        lat += time.perf_counter() - t0
        ok, tot = taux_intacts(en, table)
        intacts += ok
        total += tot
        en_final = restaurer(en, table)
        for e in ENCODAGES:
            a, b = compter(t, e), compter(en_final, e)
            if a is None or b is None:
                tok[e] = None
            elif tok[e] is not None:
                tok[e][0] += a
                tok[e][1] += b
        for k, v in termes_preserves(en_final, TERMES).items():
            if termes_preserves(t, [k])[k]:
                termes[k][0] += 1
                termes[k][1] += int(v)
        if len(echant) < 20:
            retro = restaurer(en_fr(masque_en(en)), table) if en_fr else None
            echant.append({"fr": t[:600], "en": en_final[:600], "retro_fr": (retro or "")[:600]})
    gain = {e: (None if v is None or not v[0] else round(100 * (v[0] - v[1]) / v[0], 2)) for e, v in tok.items()}
    return {"volet": nom, "n": len(textes), "tokens_fr_en": tok, "gain_pct": gain,
            "latence_s_total": round(lat, 2), "identifiants": {"intacts": intacts, "total": total,
            "taux": None if not total else round(intacts / total, 4)},
            "termes_critiques_source_vs_preserve": termes, "echantillons": echant}


def masque_en(texte):
    return texte


def setup():
    py = VENV / "Scripts" / "python.exe"
    if not py.is_file():
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    subprocess.check_call([str(py), "-m", "pip", "install", "ctranslate2", "sentencepiece", "tiktoken", "psutil",
                           "transformers", "torch", "sacremoses"])
    for sens in ("opus-mt-fr-en", "opus-mt-en-fr"):
        out = MODELES / sens
        if not out.is_dir():
            subprocess.check_call([str(VENV / "Scripts" / "ct2-transformers-converter.exe"), "--model",
                                   f"Helsinki-NLP/{sens}", "--output_dir", str(out), "--quantization", "int8",
                                   "--copy_files", "source.spm", "target.spm"])


def main():
    if "--setup" in sys.argv:
        return setup()
    jour = date.today().isoformat()
    rapport = {"date": jour, "approximation_tokenizer": "o200k_base et cl100k_base ne sont PAS le tokenizer Claude (non public)",
               "statut": "OK", "volets": []}
    try:
        ram0 = _ram_mo()
        fr_en, en_fr = Traducteur("opus-mt-fr-en"), Traducteur("opus-mt-en-fr")
        ram1 = _ram_mo()
        rapport["ram_ajoutee_mo"] = None if ram0 is None or ram1 is None else round(ram1 - ram0)
    except Exception as e:
        rapport["statut"] = f"ILLISIBLE: {type(e).__name__}: {e}"
        fr_en = en_fr = None
    if fr_en:
        v1 = corpus_volet1()
        v2 = corpus_volet2()
        t3, s3 = corpus_volet3()
        for nom, tx in (("1_prompts_owner", v1), ("2_documents_residents", [t for _, t in v2]),
                        ("3a_consignes_executeurs", t3), ("3b_sorties_outils_hub", s3)):
            rapport["volets"].append(mesurer_volet(nom, tx, fr_en, en_fr) if tx else {"volet": nom, "n": 0, "statut": "ILLISIBLE: corpus vide"})
    sortie = WORK / f"bench_traduction_{jour}.json"
    sortie.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    md = RACINE / "docs" / "mesures" / f"bench_traduction_{jour}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    L = [f"# Bench traduction FR->EN ({jour})", "", f"Statut : {rapport['statut']}. Tokenizers = approximations (pas celui de Claude).",
         "", "| Volet | n | gain o200k % | gain cl100k % | ids intacts | latence s |", "|---|---|---|---|---|---|"]
    for v in rapport["volets"]:
        if "gain_pct" in v:
            i = v["identifiants"]
            L.append(f"| {v['volet']} | {v['n']} | {v['gain_pct']['o200k_base']} | {v['gain_pct']['cl100k_base']} | {i['intacts']}/{i['total']} | {v['latence_s_total']} |")
        else:
            L.append(f"| {v['volet']} | 0 | ILLISIBLE | ILLISIBLE | - | - |")
    L += ["", f"RAM ajoutee (Mo) : {rapport.get('ram_ajoutee_mo', 'ILLISIBLE')}", "",
          "| Affirmation | Preuve | Etat |", "|---|---|---|",
          f"| Gain de tokens | comptage tiktoken ci-dessus, JSON {sortie.name} | {'MESURE' if rapport['statut'] == 'OK' else 'ILLISIBLE'} |"]
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"statut": rapport["statut"], "json": str(sortie), "md": str(md)}))


if __name__ == "__main__":
    main()
