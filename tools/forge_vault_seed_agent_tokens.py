"""tools/forge_vault_seed_agent_tokens.py — Vault seeding agent tokens.

Migre les bearer tokens hub depuis l'environnement (env vars OU Nokido.env)
vers le coffre DPAPI machine-wide via `app/forge_secrets.set_secret()`.

Conçu pour ne PAS contenir de valeurs en clair dans le code source — lecture
uniquement depuis l'environnement ou un fichier d'entrée fourni par l'utilisateur.

Sources de valeurs (par priorité) :
  1. `--from-env-file <path>` : fichier KEY=VALUE
  2. `--from-env` : os.environ (variables exportées)
  3. `--from-stdin` : KEY=VALUE par ligne sur stdin

Usage:
    # Depuis Nokido.env (chemin par défaut au-dessus du repo)
    LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py --from-env-file Nokido.env

    # Depuis env vars exportées (CI / one-shot)
    set FORGE_TOKEN_CLAUDE=...
    set FORGE_TOKEN_GEMINI=...
    LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py --from-env

    # Vérifier l'état actuel du vault sans rien modifier
    LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py --verify

    # Dry-run
    LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py --from-env --dry-run

Idempotent : skip si vault contient déjà la valeur attendue.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Liste des clés vault attendues (cohérente avec nokido_hub.py _AGENT_LIST
# + forge_secrets.diagnostic() known list).
# DERIVE MESUREE le 2026-09-02 : cette liste est CODEE EN DUR alors que le parc
# reel vit dans `config/agent_identities.json`. Consequence : VIBE, MAMMOUTH et
# ANTIGRAVITY en etaient absents — ANTIGRAVITY avait pourtant deja un token au
# coffre, et VIBE s'authentifiait donc avec le MAITRE, qui conserve l'agent du
# header et son ring (`via=master_token`). Un porteur du maitre peut se declarer
# n'importe quel agent : ce n'est pas une identite, c'est un passe-partout.
# A INSTRUIRE : faire deriver cette liste du registre plutot que la maintenir a
# la main, sinon le meme ecart reviendra au prochain client ajoute.
EXPECTED_KEYS = [
    "FORGE_TOKEN_VIBE",          # mistral-vibe (ring 2)
    "FORGE_TOKEN_MAMMOUTH",      # fork opencode (ring 3)
    "FORGE_TOKEN_OPENCODE",      # opencode servi par le lanceur :7400 (ring 3, 2026-09-25)
    "FORGE_TOKEN_ANTIGRAVITY",   # AGY = GEMINI = ANTIGRAVITY, un seul acteur
    "FORGE_TOKEN_ZCODE",
    "FORGE_MCP_TOKEN",
    "FORGE_TOKEN_CLAUDE",
    "FORGE_TOKEN_GEMINI",
    "FORGE_TOKEN_CODEX",
    "FORGE_TOKEN_CLINE",
    "FORGE_TOKEN_BRIDGE",
    "FORGE_TOKEN_COLLAB_BROKER",
    "FORGE_TOKEN_GEMINI_HEADLESS",
    "FORGE_TOKEN_CLAUDE_CLI",
    "FORGE_TOKEN_NETCFG",
    "FORGE_TOKEN_TRAY",
    "FORGE_TOKEN_SERVICES",
    "FORGE_TOKEN_LLAMACPP",
    "FORGE_TOKEN_CLAUDE_DESKTOP",
    "FORGE_TOKEN_VSCODE",
    "FORGE_TOKEN_LMSTUDIO",
    "NETCFG_MCP_TOKEN",
]


def _cles_du_registre(ring_max: int = 3) -> list[str]:
    """Clefs vault DERIVEES du registre vivant -- le correctif que le
    commentaire ci-dessus reclamait, et l'ecart s'est reproduit le jour meme :
    SUPERVISOR a ete declare au registre le 2026-09-02 et ce semeur ne le
    voyait pas, parce que sa liste est figee quand le chargeur du hub, lui,
    fait l'UNION du tuple et du registre.

    Filtre `ring_max=3` : une identite au plancher (ring 4) n'a aucun droit
    au-dessus de l'anonyme, donc lui semer un jeton n'ajoute rien -- les 15
    hooks sont dans ce cas par conception. Le filtre est DECLARE et affiche,
    pas silencieux : sans ca, « le registre est couvert » se lirait a tort.

    Registre illisible -> liste VIDE et on le DIT : l'appelant ne doit pas lire
    « rien a ajouter » quand la verite est « je n'ai pas pu regarder ».
    """
    import json as _json

    reg = Path(__file__).resolve().parent.parent / "config" / "agent_identities.json"
    try:
        agents = (_json.loads(reg.read_text(encoding="utf-8")) or {}).get("agents") or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[gen] registre ILLISIBLE ({type(exc).__name__}) -- "
              f"derivation impossible, seule la liste figee est couverte")
        return []
    out = []
    for nom, meta in sorted(agents.items()):
        try:
            if int(meta.get("ring", 4)) <= ring_max:
                out.append(f"FORGE_TOKEN_{nom}")
        except (TypeError, ValueError):
            continue
    return out


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file (Nokido.env format)."""
    out: dict[str, str] = {}
    if not path.exists():
        print(f"[err] env file not found: {path}", file=sys.stderr)
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in EXPECTED_KEYS and v:
            out[k] = v
    return out


def _parse_stdin() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in EXPECTED_KEYS and v:
            out[k] = v
    return out


def _from_environ() -> dict[str, str]:
    return {k: os.environ[k] for k in EXPECTED_KEYS if os.environ.get(k)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--from-env", action="store_true", help="Lire depuis os.environ")
    src.add_argument("--from-env-file", type=Path, help="Lire depuis un fichier KEY=VALUE")
    src.add_argument("--from-stdin", action="store_true", help="Lire depuis stdin")
    p.add_argument("--dry-run", action="store_true", help="Afficher sans écrire")
    p.add_argument("--verify", action="store_true", help="État vault, exit")
    p.add_argument(
        "--overwrite", action="store_true",
        help="Ecraser meme si le coffre a deja une valeur. Avec --generate-missing, "
             "c'est une ROTATION : la clef existante recoit une nouvelle valeur "
             "CSPRNG. Le service qui portait l'ancienne cesse d'etre reconnu tant "
             "qu'il n'a pas relu le coffre -- redemarrage requis.",
    )
    p.add_argument(
        "--agents", default="",
        help="Restreint aux agents nommes (virgules). Sans ce filtre, "
             "--generate-missing couvre la liste figee ET le registre vivant, "
             "ce qui peut semer des dizaines de jetons d'un coup.",
    )
    p.add_argument(
        "--from-registre", action="store_true",
        help="Ajoute les identites du registre vivant (ring <= --ring-max) aux "
             "clefs attendues. Sans lui, une identite declaree au registre mais "
             "absente de la liste figee ne recoit JAMAIS de jeton.",
    )
    p.add_argument(
        "--ring-max", type=int, default=3,
        help="Ring le plus eleve inclus par --from-registre (defaut 3). "
             "Le passer a 4 inclut le plancher : justifie quand une identite "
             "ring 4 porte AUJOURD'HUI le jeton d'un AUTRE organe -- lui donner "
             "le sien la ramene a son propre ring, ce qui est un durcissement. "
             "Mesure 2026-09-02 : CLAUDE_HOOK portait FORGE_TOKEN_CLAUDE tout "
             "en se declarant CLAUDE_HOOK.",
    )
    p.add_argument(
        "--generate-missing", action="store_true",
        help="Genere un token OPAQUE 256 bits (CSPRNG) pour chaque agent SANS valeur au "
             "coffre. N'ecrase jamais un token existant. La valeur ne quitte pas le "
             "process : ni argument, ni fichier, ni journal.",
    )
    args = p.parse_args()

    from nokido_agent.app.forge_secrets import get_secret, set_secret  # type: ignore

    if args.generate_missing:
        # POURQUOI ICI et pas dans un second outil : la convention FORGE_TOKEN_<AGENT>
        # a UNE seule autorite. Mesure 2026-09-02 : VIBE et MAMMOUTH n'avaient aucun
        # token derive, donc s'authentifiaient avec le MAITRE -- or le maitre conserve
        # l'agent du header et son ring (`via=master_token`), c'est un passe-partout
        # d'identite : un porteur pouvait se declarer CLAUDE et prendre son ring.
        #
        # ATTENTION, chemin d'erreur MUET mesure le meme jour : `set_secret` peut
        # ECHOUER sans lever (permission refusee sur data/machine_vault.dat) -- il
        # imprime et rend la main. On RELIT donc systematiquement, et un semis non
        # relu est rapporte comme ECHEC.
        import secrets as _secrets

        # Perimetre : liste figee, plus le registre vivant si demande, moins ce
        # que le filtre ecarte. Les trois nombres sont AFFICHES -- une couverture
        # qu'on ne chiffre pas se lit toujours comme complete.
        cles = list(EXPECTED_KEYS)
        depuis_registre = 0
        if args.from_registre:
            sup = [k for k in _cles_du_registre(args.ring_max) if k not in cles]
            depuis_registre = len(sup)
            cles += sup
        if args.agents:
            vises = {a.strip().upper() for a in args.agents.split(",") if a.strip()}
            avant = len(cles)
            cles = [k for k in cles if k.replace("FORGE_TOKEN_", "") in vises]
            print(f"[gen] filtre --agents : {len(cles)} retenue(s) sur {avant}")
            introuvables = vises - {k.replace("FORGE_TOKEN_", "") for k in cles}
            if introuvables:
                # Ne PAS passer sous silence un agent demande qu'on ne sait pas
                # placer : sinon « rien a faire » se confond avec « nom inconnu ».
                print(f"[gen] AGENT(S) NON TROUVE(S) dans le perimetre : "
                      f"{sorted(introuvables)} -- ajouter --from-registre, ou "
                      f"declarer l'identite au registre d'abord")
        print(f"[gen] perimetre : {len(cles)} clef(s) "
              f"({len(EXPECTED_KEYS)} figee(s) + {depuis_registre} du registre, "
              f"ring <= {args.ring_max})")

        rc = 0
        for key in cles:
            if get_secret(key) and not args.overwrite:
                print(f"[gen] {key:<35} DEJA PRESENT — intouche")
                continue
            # ROTATION (--overwrite), ajoutee le 2026-09-18 apres usage reel.
            # L'outil savait SEMER et pas ROTER : `if get_secret(key): continue`
            # rendait la rotation impossible par cette voie, alors que c'est
            # exactement le geste qu'on doit pouvoir faire vite quand un jeton a
            # ete expose. Ce jour-la, un NR dont la substitution de coffre ne
            # mordait pas a lu le VRAI jeton WEBHUB, et pytest l'a imprime dans
            # son diff d'echec ; il a fallu le remplacer.
            #
            # Le remplacement reste OPAQUE et local : valeur CSPRNG generee ici,
            # jamais passee en argument, jamais journalisee, relue apres ecriture
            # comme un semis ordinaire. `--overwrite` doit rester EXPLICITE : sans
            # lui on n'ecrase rien, une rotation par megarde couperait le service
            # qui portait l'ancienne valeur.
            if get_secret(key):
                print(f"[gen] {key:<35} ROTATION demandee (--overwrite)")
            val = _secrets.token_hex(32)          # 256 bits, opaque, CSPRNG
            if args.dry_run:
                print(f"[gen] {key:<35} SERAIT GENERE (dry-run)")
                continue
            # RELIRE LA VALEUR, pas la presence (mesure 2026-09-28) : une ecriture REFUSEE
            # sans lever (garde des noms reserves) laissait l'ANCIENNE valeur, et
            # `if get_secret(key)` imprimait « SEME et RELU ». On garde une EMPREINTE de ce
            # qu'on ecrit -- jamais la valeur -- et on la compare a ce qu'on relit.
            empreinte = hashlib.sha256(val.encode("utf-8")).digest()
            try:
                ecrit = set_secret(key, val)
            except Exception as e:  # noqa: BLE001
                print(f"[gen] {key:<35} ECHEC set_secret: {type(e).__name__}: {e}",
                      file=sys.stderr)
                rc = 1
                continue
            finally:
                val = None
            relu = get_secret(key)
            if ecrit is not False and relu and hashlib.sha256(relu.encode("utf-8")).digest() == empreinte:
                print(f"[gen] {key:<35} SEME et RELU")
            else:
                print(f"[gen] {key:<35} NON ECRIT -- refuse ou sans effet "
                      f"({'l ancienne valeur reste' if relu else 'aucune valeur'})", file=sys.stderr)
                rc = 1
        return rc

    if args.verify:
        print("[verify] Vault state for agent tokens:")
        # Plus AUCUNE fin de jeton (2026-09-28) : les 6 derniers caracteres affiches ici
        # etaient une fuite partielle ; la presence suffit a ce controle.
        for key in EXPECTED_KEYS:
            print(f"  {key:<35} {'OK' if get_secret(key) else 'MISSING'}")
        return 0

    # Pick source
    if args.from_env_file:
        values = _parse_env_file(args.from_env_file)
        src_label = f"file:{args.from_env_file}"
    elif args.from_stdin:
        values = _parse_stdin()
        src_label = "stdin"
    elif args.from_env:
        values = _from_environ()
        src_label = "os.environ"
    else:
        # Default: try Nokido.env adjacent to repo root
        default_path = ROOT / "Nokido.env"
        values = _parse_env_file(default_path)
        src_label = f"default:{default_path}"

    if not values:
        print(
            f"[err] no values found from source ({src_label}). "
            f"Need at least one of {EXPECTED_KEYS} as KEY=VALUE.",
            file=sys.stderr,
        )
        return 1

    print(f"[info] source={src_label} keys_found={sorted(values.keys())}", file=sys.stderr)

    n_set, n_skip, n_fail = 0, 0, 0
    for key in EXPECTED_KEYS:
        new_val = values.get(key)
        if not new_val:
            continue
        current = get_secret(key)
        if current == new_val:
            print(f"[skip] {key} already set correctly")
            n_skip += 1
            continue
        if current and not args.overwrite:
            print(f"[warn] {key} present but DIFFERENT value in vault -- use --overwrite to rotate")
            n_skip += 1
            continue
        if args.dry_run:
            print(f"[dry-run] would set {key}")
            n_set += 1
            continue
        if set_secret(key, new_val) and get_secret(key) == new_val:
            print(f"[set]  {key} -> vault (relu identique)")
            n_set += 1
        else:
            print(f"[FAIL] {key} NON ECRIT -- refuse ou sans effet")
            n_fail += 1

    print(f"\n[done] set={n_set} skip={n_skip} fail={n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
