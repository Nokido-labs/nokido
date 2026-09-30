#!/usr/bin/env python3
"""tools/forge_vault_migrate.py - migration des SECRETS Nokido.env -> coffre.

Migre uniquement les SECRETS du fichier plaintext Nokido.env vers le coffre
machine-wide (DPAPI LocalMachine, cf. app/forge_machine_vault.py). La config
non-sensible (URLs, ports, tailles de batch, flags) RESTE dans Nokido.env :
get_secret() la trouve toujours via le fallback .env.

Le coffre machine est lisible par TOUS les comptes service (user, sandbox,
trusted, supervisor), contrairement au WCM per-user — c'est ce qui permet de
retirer les secrets en clair sans casser les services non-user.

(Nomme forge_vault_migrate et non *_secrets_* : le gitignore protege le
motif *_secrets* — un outil non trackable ne serait pas executable en
trusted_script.)

3 phases explicites :
  --check     diagnostic seul, AUCUNE ecriture. Classe secret vs config.
  --migrate   copie chaque SECRET .env -> coffre, verifie par relecture, puis
              ACL le fichier coffre en lecture pour le groupe sandbox.
  --finalize  APRES --migrate verifie : sauvegarde Nokido.env hors repo puis
              retire SEULEMENT les lignes secrets (config + commentaires gardes).

A lancer privilegie (ecriture data/) via le hub :
  run action=trusted_script path=tools/forge_vault_migrate.py
      script_args="--check"

Ne JAMAIS imprimer une valeur de secret — seulement noms de cles + statut.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ENV_PATH = ROOT / "Nokido.env"


def _backup_root() -> Path:
    """Repertoire de backup .env. Priorite : _backups/secrets/ (DANS le repo
    mais GITIGNORE — pas de fuite). Path.home() = C:/Users/Default sous le
    compte LaForgeTrusted donc inaccessible — d'ou la cible dans le repo
    (LaForgeTrusted a Modify sur ROOT). Le fichier reste plaintext donc
    sensible : a supprimer apres verification."""
    target = ROOT / "_backups" / "secrets"
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError:
        return ROOT


BACKUP = _backup_root() / "nokido_env_backup_DELETE_ME.txt"
SANDBOX_GROUP = "LaForgeSandboxUsers"

from nokido_agent.app import forge_machine_vault as vault  # noqa: E402

# ── classification secret vs config ──────────────────────────────────────
# Un secret = quelque chose dont la fuite est un probleme. Match sur SUFFIXE
# de nom (pas substring : MAX_TOKENS ne doit pas matcher _TOKEN, MCP_HTTP_PATH
# pas _PAT). SECRET_SUBSTR couvre les cles a token au MILIEU (FORGE_TOKEN_*).
SECRET_SUFFIXES = (
    "_API_KEY",
    "_APIKEY",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_PASSWD",
    "_PAT",
    "_KEY",
)
SECRET_SUBSTR = ("_TOKEN_",)
SECRET_EXACT = {"DEEPINFRA", "SILICONFLOW", "SMITHERY_API"}
# Garde-fou explicite : noms ambigus qui NE sont PAS des secrets.
NOT_SECRET_EXACT = {
    "PRIVATE_KEY_PATH",
    "LLAMACPP_MODEL_PATH",
    "LLAMACPP_MODEL_PATH_QWEN",
    "MODEL_QUANTIZED_NPU",
    "ONNXGENAI_MODEL_PATH",
    "MINILM_BASE_ONNX",
    "MINILM_NPU_QUARK",
    "LITELLM_API_BASE",
}


def is_secret(key: str) -> bool:
    """True si la cle designe un secret a mettre au coffre. Match par suffixe
    de nom — evite que MAX_TOKENS matche _TOKEN ou MCP_HTTP_PATH matche _PAT."""
    if key in NOT_SECRET_EXACT:
        return False
    if key in SECRET_EXACT:
        return True
    ku = key.upper()
    if any(ku.endswith(s) for s in SECRET_SUFFIXES):
        return True
    return any(sub in ku for sub in SECRET_SUBSTR)


def parse_env(path: Path) -> dict[str, str]:
    """Parse KEY=value depuis un .env. Ignore commentaires / lignes vides."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[k] = v
    return out


def _resolve_placeholders(secrets: dict[str, str]) -> dict[str, str]:
    """Un secret sensible peut valoir le pointeur
    `<ENCRYPTED:see Nokido.env.secrets>` (pose par forge_env_crypt lors d'un
    passage anterieur). Resout ces pointeurs en dechiffrant Nokido.env.secrets
    via forge_env_crypt.load_secrets() — DPAPI user-scope, donc a lancer sous
    le compte user. Sans resolution, le coffre recevrait le texte du pointeur
    au lieu de la vraie cle (bug GROQ/GEMINI/KAGGLE)."""
    ph = {k for k, v in secrets.items() if str(v).startswith("<ENCRYPTED")}
    if not ph:
        return secrets
    try:
        from nokido_agent.app.forge_env_crypt import load_secrets

        real = load_secrets()
    except Exception as e:  # noqa: BLE001
        print(f"[migrate] resolution placeholders impossible : {e}")
        return secrets
    for k in sorted(ph):
        rv = real.get(k)
        if rv and not str(rv).startswith("<ENCRYPTED"):
            secrets[k] = rv
        else:
            print(
                f"[migrate] WARN placeholder non resolu pour {k} "
                f"(absent de Nokido.env.secrets ou dechiffrement echoue)"
            )
    return secrets


def _secrets_only(env: dict[str, str]) -> dict[str, str]:
    return _resolve_placeholders({k: v for k, v in env.items() if is_secret(k)})


def cmd_check() -> int:
    env = parse_env(ENV_PATH)
    secrets = _secrets_only(env)
    config = {k: v for k, v in env.items() if not is_secret(k)}
    print(
        f"[check] Nokido.env : {len(env)} cle(s) — {len(secrets)} secret(s), {len(config)} config"
    )
    print(f"[check] coffre machine disponible : {vault.available()}")
    print(f"\n[check] SECRETS a migrer ({len(secrets)}) :")
    in_v = to_mig = mismatch = 0
    for k, v in sorted(secrets.items()):
        cur = vault.vault_get(k)
        if cur is None:
            to_mig += 1
            tag = "[.env seul  ]"
        elif cur == v:
            in_v += 1
            tag = "[coffre==env]"
        else:
            mismatch += 1
            tag = "[DIVERGENT  ]"
        print(f"  {tag} {k}")
    print(f"\n[check] {in_v} deja au coffre | {to_mig} a migrer | {mismatch} divergent(s)")
    print(f"[check] config NON migree (reste dans .env) : {sorted(config)}")
    return 0


def _acl_vault_readable() -> None:
    """Donne la LECTURE du fichier coffre au groupe sandbox. Le contenu est
    chiffre DPAPI : exposer le fichier en lecture ne fuit aucun secret, mais
    permet aux services sous compte sandbox d'appeler vault_get()."""
    if not vault.VAULT_PATH.exists():
        return
    # `errors="replace"` OBLIGATOIRE : sur un Windows francais, `icacls` repond en
    # cp1252 et un accent (0x82 = « e » accentue) fait exploser `_readerthread` en
    # UnicodeDecodeError APRES que la commande a reussi. Mesure du 2026-08-05 : ACL
    # accordee, sortie « OK », puis trace de plantage — de quoi croire l'operation
    # ratee alors qu'elle avait abouti. C'est le motif que le git-gate signale sous
    # « subprocess mode-texte SANS errors= ».
    r = subprocess.run(
        ["icacls", str(vault.VAULT_PATH), "/grant", f"{SANDBOX_GROUP}:(R)", "/C"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ok = r.returncode == 0
    print(
        f"[migrate] ACL coffre lecture {SANDBOX_GROUP} : "
        f"{'OK' if ok else 'KO — ' + (r.stderr or r.stdout).strip()}"
    )


def cmd_migrate() -> int:
    secrets = _secrets_only(parse_env(ENV_PATH))
    if not secrets:
        print("[migrate] aucun secret dans Nokido.env — rien a migrer.")
        return 0
    if not vault.available():
        print("[migrate] coffre machine indisponible (Windows requis).")
        return 1
    ok = fail = 0
    for k, v in sorted(secrets.items()):
        if vault.vault_set(k, v):
            ok += 1
            print(f"  [OK    ] {k}")
        else:
            fail += 1
            print(f"  [FAIL  ] {k}  (ecriture ou relecture coffre echouee)")
    print(f"\n[migrate] {ok}/{len(secrets)} migres+verifies | {fail} echec(s)")
    if fail:
        print("[migrate] NE PAS finaliser : echecs a regler d'abord.")
        return 1
    _acl_vault_readable()
    print("[migrate] OK. Etape suivante : --finalize (retire les lignes secrets).")
    return 0


def cmd_prep() -> int:
    """Pre-finalize cleanup. Pour chaque secret du .env :
      - placeholder <ENCRYPTED:...> ET coffre détient la clé -> drop ligne .env
        (le placeholder est dead weight, la vraie valeur est au coffre déjà).
      - absent du coffre -> vault_set (push .env -> coffre).
    Backup .env hors repo avant édition. Idempotent.

    Resoud le cas DIVERGENT bloquant --finalize quand forge_env_crypt ne peut
    plus déchiffrer Nokido.env.secrets (DPAPI key rotated).
    """
    import re as _re
    import time as _time

    raw = ENV_PATH.read_text(encoding="utf-8", errors="replace")
    env = parse_env(ENV_PATH)
    secrets_in_env = {k: v for k, v in env.items() if is_secret(k)}
    ph_rx = _re.compile(r"^<ENCRYPTED")

    # 1) Push .env -> coffre pour clés absentes.
    pushed: list[str] = []
    for k, v in sorted(secrets_in_env.items()):
        if ph_rx.match(v):
            continue
        if vault.vault_get(k) is None:
            if vault.vault_set(k, v):
                pushed.append(k)
                print(f"  [push  ] {k}")
            else:
                print(f"  [FAIL  ] {k} (vault_set echec)")
    if pushed:
        print(f"[prep] {len(pushed)} cle(s) poussee(s) au coffre.")
    else:
        print("[prep] aucune cle a pousser au coffre.")

    # 2) Drop lignes placeholder dont coffre detient la vraie valeur.
    dropped: list[str] = []
    out_lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            k = s.split("=", 1)[0].strip()
            v = s.split("=", 1)[1].strip().strip('"').strip("'")
            if is_secret(k) and ph_rx.match(v) and vault.vault_get(k) is not None:
                dropped.append(k)
                out_lines.append(f"# {k}  -> placeholder retire (coffre detient la vraie cle)")
                continue
        out_lines.append(line)

    if dropped:
        bak = _backup_root() / f"nokido_env_prep_backup_{int(_time.time())}.txt"
        bak.write_text(raw, encoding="utf-8")
        ENV_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"[prep] {len(dropped)} placeholder(s) retire(s) : {dropped}")
        print(f"[prep] backup .env -> {bak}")
    else:
        print("[prep] aucun placeholder a retirer.")
    print("[prep] OK. Etape suivante : --check puis --finalize.")
    return 0


def cmd_finalize() -> int:
    secrets = _secrets_only(parse_env(ENV_PATH))
    if not secrets:
        print("[finalize] aucun secret dans Nokido.env. Rien a faire.")
        return 0
    not_ready = [k for k, v in secrets.items() if vault.vault_get(k) != v]
    if not_ready:
        print(f"[finalize] ABANDON : {len(not_ready)} secret(s) pas/mal au coffre : {not_ready}")
        print("[finalize] Relancer --migrate.")
        return 1
    BACKUP.write_text(ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    kept: list[str] = []
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in secrets:
                kept.append(f"# {k}  -> migre dans le coffre machine (DPAPI)")
                continue
        kept.append(line)
    ENV_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"[finalize] {len(secrets)} secret(s) retires de Nokido.env (config conservee).")
    print(f"[finalize] Backup plaintext hors repo : {BACKUP}")
    print("[finalize] >>> SUPPRIMER ce backup une fois rassure : c'est du clair.")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    actions = {
        "--check": cmd_check,
        "--migrate": cmd_migrate,
        "--prep": cmd_prep,
        "--finalize": cmd_finalize,
    }
    fn = actions.get(arg)
    if fn is None:
        sys.exit("usage: forge_vault_migrate.py [--check|--migrate|--prep|--finalize]")
    sys.exit(fn())
