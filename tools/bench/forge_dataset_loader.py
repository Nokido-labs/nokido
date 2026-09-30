"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_dataset_loader
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
"""
forge_dataset_loader.py — Télécharge et prépare des datasets pour le RAG de La Forge.

Usage :
    python forge_dataset_loader.py --all              # tout télécharger
    python forge_dataset_loader.py --docs              # docs techniques seulement
    python forge_dataset_loader.py --code              # paires code Python seulement
    python forge_dataset_loader.py --sysadmin          # docs sysadmin/DevOps seulement

Les fichiers sont écrits dans rag_files/ pour ingestion automatique au warmup.

Prérequis :
    pip install requests --break-system-packages
    (optionnel) pip install datasets --break-system-packages  # pour HuggingFace
"""

import json
import re
import time
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
RAG_DIR = SCRIPT_DIR.parent / "data" / "rag_files"
GOLD_DIR = SCRIPT_DIR.parent / "data"
RAG_DIR.mkdir(parents=True, exist_ok=True)

# Nombre max de fichiers par catégorie (pour ne pas exploser le RAG)
MAX_DOCS_PER_CATEGORY = 50
MAX_CODE_PAIRS = 500


# =============================================================================
# 1. DOCUMENTATION TECHNIQUE — Sources directes (Markdown/Text)
# =============================================================================

# URLs de docs techniques en markdown/texte brut (GitHub raw)
TECH_DOCS = {
    # ── Réseau / VPN ──
    "wireguard": [
        "https://raw.githubusercontent.com/pirate/wireguard-docs/master/README.md",
    ],
    # ── Web / Reverse Proxy ──
    "nginx": [
        "https://raw.githubusercontent.com/trimstray/nginx-admins-handbook/master/doc/RULES.md",
        "https://raw.githubusercontent.com/trimstray/nginx-admins-handbook/master/doc/HELPERS.md",
    ],
    # ── Conteneurs ──
    "docker": [
        "https://raw.githubusercontent.com/wsargent/docker-cheat-sheet/master/README.md",
    ],
    "kubernetes": [
        "https://raw.githubusercontent.com/dennyzhang/cheatsheet-kubernetes-A4/master/README.org",
    ],
    # ── Système ──
    "systemd": [
        "https://raw.githubusercontent.com/jsynacek/systemd-fundamentals/master/README.md",
    ],
    "linux_commands": [
        "https://raw.githubusercontent.com/jlevy/the-art-of-command-line/master/README.md",
    ],
    # ── Sécurité ──
    "fail2ban": [
        "https://raw.githubusercontent.com/fail2ban/fail2ban/master/README.md",
    ],
    # ── Python ──
    "python_best_practices": [
        "https://raw.githubusercontent.com/realpython/python-guide/master/docs/writing/style.rst",
        "https://raw.githubusercontent.com/realpython/python-guide/master/docs/writing/structure.rst",
    ],
    "asyncio": [
        "https://raw.githubusercontent.com/python/cpython/main/Doc/library/asyncio-task.rst",
    ],
    # ── DevOps ──
    "ansible": [
        "https://raw.githubusercontent.com/ansible/ansible/devel/README.md",
    ],
    "terraform": [
        "https://raw.githubusercontent.com/hashicorp/terraform/main/README.md",
    ],
    # ── Monitoring ──
    "prometheus": [
        "https://raw.githubusercontent.com/prometheus/prometheus/main/README.md",
    ],
    "grafana": [
        "https://raw.githubusercontent.com/grafana/grafana/main/README.md",
    ],
}


def fetch_url(url: str, timeout: int = 15) -> str:
    """Télécharge le contenu texte d'une URL."""
    import requests

    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "LaForge-DatasetLoader/1.0"})
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  ⚠ {url[:60]}… : {e}")
        return ""


def download_tech_docs() -> list[dict]:
    """Télécharge les docs techniques et les écrit dans rag_files/."""
    print("\n═══ 1. Documentation technique ═══")
    total = 0
    for category, urls in TECH_DOCS.items():
        for i, url in enumerate(urls):
            fname = f"doc_{category}_{i}.md"
            fpath = RAG_DIR / fname
            if fpath.exists() and fpath.stat().st_size > 100:
                print(f"  ✓ {fname} (déjà présent)")
                total += 1
                continue
            print(f"  ↓ {category} → {url[:60]}…")
            content = fetch_url(url)
            if content and len(content) > 200:
                # Nettoyer le markdown
                content = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", content)  # badges
                content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)  # commentaires HTML
                # Header pour le RAG
                header = f"# {category.upper()} — Documentation technique\nSource: {url}\n---\n\n"
                fpath.write_text(header + content[:50000], encoding="utf-8")
                print(f"  ✅ {fname} ({len(content):,} chars)")
                total += 1
            else:
                print(f"  ❌ {category} — contenu vide")
            time.sleep(0.3)  # rate limiting
    print(f"\n  Total docs techniques : {total}")
    return total


# =============================================================================
# 2. PAIRES CODE PYTHON — Pour le fine-tuning et le RAG code
# =============================================================================


def download_code_pairs() -> list[dict]:
    """
    Télécharge des paires (description, code Python) depuis des sources ouvertes.
    Format gold_samples.jsonl compatible.
    """
    print("\n═══ 2. Paires code Python ═══")

    # ── Source 1 : Python snippets structurés ──
    # On génère des paires à partir de docstrings extraites de la stdlib
    stdlib_modules = [
        "os",
        "sys",
        "pathlib",
        "json",
        "re",
        "hashlib",
        "asyncio",
        "subprocess",
        "logging",
        "collections",
        "itertools",
        "functools",
        "datetime",
        "socket",
        "http.server",
        "urllib.parse",
        "shutil",
        "threading",
        "multiprocessing",
        "configparser",
        "argparse",
    ]

    gold_path = GOLD_DIR / "gold_samples_base.jsonl"
    pairs_written = 0

    with open(gold_path, "a", encoding="utf-8") as gf:
        for mod_name in stdlib_modules:
            try:
                mod = __import__(mod_name)
                for attr_name in dir(mod):
                    if attr_name.startswith("_"):
                        continue
                    obj = getattr(mod, attr_name, None)
                    if not callable(obj):
                        continue
                    doc = getattr(obj, "__doc__", "") or ""
                    if len(doc) < 50:
                        continue
                    # Créer une paire description → usage
                    pair = {
                        "timestamp": "2026-03-08T00:00:00",
                        "version": "stdlib",
                        "target": f"{mod_name}.{attr_name}",
                        "description": doc[:300].split("\n")[0].strip(),
                        "code_before": "",
                        "code_after": f"from {mod_name} import {attr_name}\n# {doc[:100]}",
                        "validated": True,
                        "source": "stdlib",
                    }
                    gf.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    pairs_written += 1
                    if pairs_written >= MAX_CODE_PAIRS:
                        break
            except Exception as e:
                print(f"  ⚠ {mod_name}: {e}")
            if pairs_written >= MAX_CODE_PAIRS:
                break

    print(f"  ✅ {pairs_written} paires stdlib → {gold_path.name}")

    # ── Source 2 : HuggingFace datasets (si installé) ──
    try:
        from datasets import load_dataset

        print("  ↓ Téléchargement flytech/python-codes-25k…")
        ds = load_dataset("flytech/python-codes-25k", split="train", streaming=True)
        hf_count = 0
        with open(gold_path, "a", encoding="utf-8") as gf:
            for example in ds:
                if hf_count >= MAX_CODE_PAIRS:
                    break
                code = example.get("output", example.get("code", ""))
                desc = example.get("instruction", example.get("input", ""))
                if not code or not desc or len(code) < 30:
                    continue
                pair = {
                    "timestamp": "2026-03-08T00:00:00",
                    "version": "hf-python25k",
                    "target": "hf_pair",
                    "description": desc[:300],
                    "code_before": "",
                    "code_after": code[:3000],
                    "validated": True,
                    "source": "flytech/python-codes-25k",
                }
                gf.write(json.dumps(pair, ensure_ascii=False) + "\n")
                hf_count += 1
        print(f"  ✅ {hf_count} paires HuggingFace → {gold_path.name}")
        pairs_written += hf_count
    except ImportError:
        print("  ℹ datasets non installé — pip install datasets pour les paires HuggingFace")
    except Exception as e:
        print(f"  ⚠ HuggingFace: {e}")

    print(f"\n  Total paires code : {pairs_written}")
    return pairs_written


# =============================================================================
# 3. DOCS SYSADMIN / DEVOPS — Cheatsheets et guides
# =============================================================================

SYSADMIN_DOCS = {
    "iptables_cheatsheet": "https://raw.githubusercontent.com/trimstray/iptables-essentials/master/README.md",
    "tmux_cheatsheet": "https://raw.githubusercontent.com/tmuxinator/tmuxinator/master/README.md",
    "git_cheatsheet": "https://raw.githubusercontent.com/arslanbilal/git-cheat-sheet/master/other-sheets/git-cheat-sheet-en.md",
    "bash_guide": "https://raw.githubusercontent.com/Idnan/bash-guide/master/README.md",
    "linux_sysadmin": "https://raw.githubusercontent.com/kahun/awesome-sysadmin/master/README.md",
    "security_checklist": "https://raw.githubusercontent.com/Lissy93/personal-security-checklist/HEAD/README.md",
    "devops_exercises": "https://raw.githubusercontent.com/bregman-arie/devops-exercises/master/README.md",
    "dns_guide": "https://raw.githubusercontent.com/trimstray/the-book-of-secret-knowledge/master/README.md",
}


def download_sysadmin_docs() -> list[dict]:
    """Télécharge les cheatsheets sysadmin/DevOps."""
    print("\n═══ 3. Docs Sysadmin / DevOps ═══")
    total = 0
    for name, url in SYSADMIN_DOCS.items():
        fname = f"sysadmin_{name}.md"
        fpath = RAG_DIR / fname
        if fpath.exists() and fpath.stat().st_size > 100:
            print(f"  ✓ {fname} (déjà présent)")
            total += 1
            continue
        print(f"  ↓ {name} → {url[:60]}…")
        content = fetch_url(url)
        if content and len(content) > 200:
            content = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", content)
            content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
            header = f"# {name.upper().replace('_', ' ')} — Sysadmin Guide\nSource: {url}\n---\n\n"
            fpath.write_text(header + content[:80000], encoding="utf-8")
            print(f"  ✅ {fname} ({len(content):,} chars)")
            total += 1
        else:
            print(f"  ❌ {name} — contenu vide")
        time.sleep(0.3)
    print(f"\n  Total docs sysadmin : {total}")
    return total


# =============================================================================
# RAPPORT
# =============================================================================


def report() -> None:
    """Affiche un résumé de ce qui est dans rag_files/."""
    print("\n═══ Rapport RAG ═══")
    if not RAG_DIR.exists():
        print("  rag_files/ introuvable")
        return
    files = sorted(RAG_DIR.glob("*"))
    total_size = 0
    categories = {}
    for f in files:
        if f.is_file():
            size = f.stat().st_size
            total_size += size
            cat = f.stem.split("_")[0]
            categories[cat] = categories.get(cat, 0) + 1
    print(f"  Fichiers : {len(files)}")
    print(f"  Taille   : {total_size:,} bytes ({total_size / 1024:.0f} Ko)")
    for cat, count in sorted(categories.items()):
        print(f"    {cat:15s} : {count} fichiers")

    # Gold samples
    for gp in [GOLD_DIR / "gold_samples.jsonl", GOLD_DIR / "gold_samples_base.jsonl"]:
        if gp.exists():
            lines = sum(1 for _ in open(gp, encoding="utf-8"))
            print(f"  {gp.name:25s} : {lines} paires")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nokido Dataset Loader")
    parser.add_argument("--all", action="store_true", help="Tout télécharger")
    parser.add_argument("--docs", action="store_true", help="Docs techniques")
    parser.add_argument("--code", action="store_true", help="Paires code Python")
    parser.add_argument("--sysadmin", action="store_true", help="Docs sysadmin/DevOps")
    parser.add_argument("--report", action="store_true", help="Rapport RAG")
    args = parser.parse_args()

    if not any([args.all, args.docs, args.code, args.sysadmin, args.report]):
        args.all = True  # par défaut : tout

    print("⚒ Nokido Dataset Loader")
    print(f"  RAG dir  : {RAG_DIR}")
    print(f"  Gold dir : {GOLD_DIR}")

    if args.all or args.docs:
        download_tech_docs()
    if args.all or args.code:
        download_code_pairs()
    if args.all or args.sysadmin:
        download_sysadmin_docs()

    report()
    print("\n✅ Terminé. Relancez La Forge pour indexer les nouvelles données.")
