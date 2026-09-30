"""
FORGE INTELLIGENCE — forge_secret_audit [GREEN]
================================================
Audit du coffre de secrets : détecte PLACEHOLDERS / clés vides / suspectes,
SANS JAMAIS imprimer les valeurs (masquage : préfixe court + longueur seulement).
Vérifie la centralisation (clés dans le vault). À lancer en trusted_script.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PLACEHOLDER_MARKS = (
    "ta_cle", "ta-cle", "tacle", "votre", "your_", "your-", "yourkey", "xxx",
    "placeholder", "changeme", "change_me", "change-me", "todo", "a_remplir",
    "à_remplir", "dummy", "example", "exemple", "test_key", "redacted", "...",
)
# Clés API attendues (fallback si pas de fonction de liste).
KNOWN_KEYS = [
    "GROQ_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "HF_TOKEN", "MISTRAL_API_KEY",
    "GEMINI_API_KEY", "CEREBRAS_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
    "COHERE_API_KEY", "KIMI_API_KEY", "OPENROUTER_API_KEY", "GLM_API_KEY",
    "SAMBANOVA_API_KEY", "NVIDIA_API_KEY", "TAVILY_API_KEY", "FORGE_MCP_TOKEN",
    "LAFORGE_ADMIN_TOKEN", "LAFORGE_SUPERVISOR_TOKEN", "LAFORGE_HUB_TOKEN",
]


def _classify(val: str | None) -> str:
    v = (val or "")
    low = v.lower()
    if not v.strip():
        return "EMPTY"
    if v.startswith("<") or v.endswith(">") or any(m in low for m in PLACEHOLDER_MARKS):
        return "PLACEHOLDER"
    if len(v) < 12:
        return "SUSPECT_SHORT"
    return "OK"


def _mask(val: str | None, verdict: str, cle: str = "") -> str:
    """Delegue a la politique UNIQUE de masquage (phase 4).

    Rendait `val[:4]` -- quatre caracteres REELS du secret, sur stdout, donc
    dans tout journal qui le capture. Le CLI de `forge_secrets` avait la meme
    faute en `val[-4:]` : la corriger la-bas ne l'avait pas corrigee ici, parce
    que chaque afficheur portait sa propre regle.

    `verdict` reste utile : il dit EMPTY / PLACEHOLDER / SUSPECT_SHORT / OK,
    ce qui est une propriete de la valeur sans etre la valeur.
    """
    try:
        from nokido_agent.tools.forge_secret_source_audit import masquer
        return "%s | %s" % (verdict, masquer(cle or "INCONNU", val))
    except Exception:          # noqa: BLE001 -- politique injoignable = on MASQUE
        return "%s | len=%s (politique de masquage injoignable)" % (
            verdict, len(val) if val else 0)


# L'ancienne `_mask` vivait ici. Elle rendait `val[:4]` pour « aider a
# identifier » : un prefixe de secret n'aide pas a identifier, il REVELE. Une
# empreinte publique remplit le meme role sans rien exposer. Elle n'est pas
# gelee mais RETIREE : une fonction morte qui fuit reste une porte qu'un
# appelant futur peut rouvrir sans le savoir. L'historique git la conserve.


FREE_TIER_TEMPLATE = """
# === FREE-TIER PROVIDERS (decommente la ligne + colle la vraie cle) ===
# SambaNova   https://cloud.sambanova.ai   (free, rapide)
#SAMBANOVA_API_KEY=
# NVIDIA NIM  https://build.nvidia.com      (credits gratuits)
#NVIDIA_API_KEY=
# Zhipu Z.ai  https://z.ai                  (GLM-4-Flash GRATUIT)
#GLM_API_KEY=
# Moonshot    https://platform.moonshot.ai  (quota free)
#KIMI_API_KEY=
# Together    https://api.together.xyz      (credits free)
#TOGETHER_API_KEY=
# Cloudflare  https://dash.cloudflare.com   (Workers AI free)
#CLOUDFLARE_API_TOKEN=
#CLOUDFLARE_ACCOUNT_ID=
"""


def add_template() -> int:
    """Ajoute la rubrique free-tier (COMMENTEE) a Nokido.env. Idempotent.
    N'imprime AUCUNE valeur ; lit le fichier seulement pour l'idempotence."""
    from nokido_agent.app import forge_secrets as fs
    env_path = Path(getattr(fs, "ENV_PATH", ROOT / "Nokido.env"))
    try:
        if "FREE-TIER PROVIDERS" in env_path.read_text(encoding="utf-8", errors="ignore"):
            print(f"rubrique deja presente dans {env_path.name}, skip")
            return 0
    except FileNotFoundError:
        pass
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(FREE_TIER_TEMPLATE)
    print(f"rubrique free-tier (commentee, 7 providers) ajoutee a {env_path.name}")
    return 0


def main() -> int:
    from nokido_agent.app import forge_secrets as fs

    api = [a for a in dir(fs) if not a.startswith("_")]
    print("forge_secrets API:", api)
    get_fn = next((getattr(fs, c) for c in ("get_secret", "get", "read_secret", "secret")
                   if hasattr(fs, c) and callable(getattr(fs, c))), None)
    list_fn = next((getattr(fs, c) for c in ("list_secrets", "secret_names", "list_keys",
                                             "all_secrets", "list", "keys")
                    if hasattr(fs, c) and callable(getattr(fs, c))), None)
    if get_fn is None:
        print("ERR: aucune fonction get_* dans forge_secrets")
        return 1

    try:
        names = sorted(set(list_fn() or [])) if list_fn else []
    except Exception as e:
        print(f"list_fn KO ({e}) -> fallback KNOWN_KEYS")
        names = []
    source = "list_fn" if names else "KNOWN_KEYS"
    if not names:
        names = KNOWN_KEYS

    print(f"\n=== AUDIT secrets (source={source}, {len(names)} clés, valeurs MASQUÉES) ===")
    bad = []
    present = 0
    for n in names:
        try:
            v = get_fn(n)
        except Exception as e:
            print(f"  [ERR]        {n}: {e}")
            continue
        if v is None or v == "":
            # absente : seulement notable si c'est une clé attendue
            if source == "KNOWN_KEYS":
                print(f"  [ABSENT]     {n}")
            continue
        present += 1
        verdict = _classify(v)
        print(f"  [{verdict:13}] {n}  ({_mask(v, verdict, n)})")
        if verdict != "OK":
            bad.append((n, verdict))

    print(f"\n=== RÉSUMÉ : {present} clés présentes, {len(bad)} problème(s) ===")
    for n, vd in bad:
        print(f"  [WARN] {n} = {vd}")
    if not bad:
        print("  [CLEAN] aucun placeholder / cle vide detecte")
    return 0


if __name__ == "__main__":
    if "--add-template" in sys.argv:
        raise SystemExit(add_template())
    raise SystemExit(main())
