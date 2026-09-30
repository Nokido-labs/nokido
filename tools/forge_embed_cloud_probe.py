# -*- coding: utf-8 -*-
"""Sonde LIVE des providers d'embedding cloud (jina / voyage / modal).

POURQUOI un outil et pas un one-liner : depuis `LaForgeSbxOffline` (compte des
jobs et de `run action=python`) tout egress rend
`WinError 10013 — socket interdit par ses autorisations`. Un provider
parfaitement sain y parait donc MORT. Mesure 2026-08-19 : jina/voyage/modal
rendaient tous `None` et `health_providers()` disait `configured` — la cause
n'etait ni le quota, ni la cle, ni le circuit breaker (tous ouverts), mais le
sandbox sans reseau. Cette sonde doit tourner en `trusted_script`
(`LaForgeTrusted`, qui a le reseau) et rend le VRAI code retour HTTP.

N'imprime JAMAIS la valeur d'un secret : presence booleenne + code HTTP seuls.

    run action=trusted_script path=tools/forge_embed_cloud_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nokido_agent.app import forge_embed_router as R  # noqa: E402

TEXTES = ["test de vectorisation souveraine Nokido",
          "second texte pour valider le batch"]


def main() -> int:
    print("=== CREDS (presence seule) ===")
    for p in ("jina", "voyage", "modal", "hf", "cloudflare"):
        try:
            print("  %-8s creds=%s  cb_ouvert=%s" % (p, R._provider_has_creds(p),
                                                     not R._cb_can_call(p)))
        except Exception as e:  # noqa: BLE001
            print("  %-8s introspection KO: %s" % (p, type(e).__name__))

    print("\n=== APPEL LIVE (batch de %d textes) ===" % len(TEXTES))
    for nom, fn in (("jina", R._jina_call), ("voyage", R._voyage_call), ("modal", R._modal_call),
                    ("cloudflare", R._cloudflare_call)):
        t0 = time.time()
        try:
            v = fn(TEXTES, timeout=25.0)
            dt = time.time() - t0
            if v and v[0]:
                print("  %-8s OK    dim=%d  n=%d  %.2fs" % (nom, len(v[0]), len(v), dt))
            else:
                print("  %-8s VIDE  %.2fs (voir cause ci-dessous)" % (nom, dt))
        except Exception as e:  # noqa: BLE001
            print("  %-8s RAISE %s: %s" % (nom, type(e).__name__, str(e)[:160]))

    # Cause exacte : appel HTTP a nu pour LIRE le code retour (401 vs 429 vs 402
    # ne se traitent pas pareil : cle morte / quota epuise / paiement requis).
    print("\n=== CAUSE HTTP EXACTE (code retour, jamais le secret) ===")
    import json
    import urllib.error
    import urllib.request

    essais = [
        ("jina", R.JINA_URL,
         {"model": "jina-embeddings-v3", "input": ["ping"], "dimensions": 1024},
         "JINA_API_KEY"),
        ("voyage", R.VOYAGE_URL,
         {"model": "voyage-3", "input": ["ping"], "output_dimension": 1024},
         "VOYAGE_API_KEY"),
        # OpenRouter sert `baai/bge-m3` -- MEME espace vectoriel que le local et que
        # Cloudflare, mais PAYANT (tarif public ~0,01 $/M jetons au 2026-09-06, soit
        # ~0,30 $ pour les ~122 000 chunks en attente a ~250 jetons piece). Sonde ici
        # pour repondre a UNE question : la route existe-t-elle vraiment pour NOTRE
        # cle, et rend-elle bien 1024 dimensions ? Tant que ce n'est pas mesure, ce
        # n'est pas un backend -- c'est une hypothese de tarif.
        ("openrouter", "https://openrouter.ai/api/v1/embeddings",
         {"model": "baai/bge-m3", "input": ["ping"]},
         "OPENROUTER_API_KEY"),
        # HF et NVIDIA servent le VRAI `BAAI/bge-m3` -- donc le meme espace vectoriel que
        # la base, contrairement a jina et voyage. Leurs cles dormaient au coffre sans
        # avoir jamais ete mesurees : une capacite non sondee n'est ni presente ni
        # absente, elle est INCONNUE.
        ("hf", "https://router.huggingface.co/hf-inference/models/BAAI/bge-m3/pipeline/feature-extraction",
         {"inputs": ["ping"]},
         "HF_TOKEN"),
        ("nvidia", "https://integrate.api.nvidia.com/v1/embeddings",
         {"model": "baai/bge-m3", "input": ["ping"], "input_type": "passage"},
         "NVIDIA_API_KEY"),
        # SiliconFlow et Nebius servent `BAAI/bge-m3` en 1024d avec une API compatible
        # OpenAI. Aucune cle au coffre a ce jour : on sonde quand meme, car un endpoint
        # se qualifie SANS compte -- 401 dit « la route existe, il manque une cle »,
        # 404 dit « cette route n'existe pas ». Confondre les deux, c'est soit ouvrir un
        # compte pour rien, soit ignorer une capacite disponible.
        # NOM EXACT DE LA CLE AU COFFRE : `SILICONFLOW`, pas `SILICONFLOW_API_KEY`
        # (mesure 2026-09-06). J'avais devine seize noms puis conclu « absente », alors
        # que le coffre porte 87 clefs et que `forge_secrets.diagnostic()` n'en coche
        # que 26, ecrites en dur. Deux instruments aveugles, un silence lu comme une
        # absence. ENUMERER (`forge_machine_vault.vault_list()`), ne jamais deviner.
        # DEUX PLATEFORMES DISTINCTES chez SiliconFlow : `.cn` (Chine) et `.com`
        # (international). Les comptes et les clefs ne sont PAS partages entre les deux,
        # et l'erreur rendue est la meme -- `401 Api key is invalid` -- ce qui fait
        # conclure « clef morte » quand on interroge simplement le mauvais domaine.
        # On sonde les DEUX : c'est le seul moyen de distinguer les deux causes.
        ("sflow.cn", "https://api.siliconflow.cn/v1/embeddings",
         {"model": "BAAI/bge-m3", "input": ["ping"]},
         "SILICONFLOW"),
        ("sflow.com", "https://api.siliconflow.com/v1/embeddings",
         {"model": "BAAI/bge-m3", "input": ["ping"]},
         "SILICONFLOW"),
        ("nebius", "https://api.studio.nebius.com/v1/embeddings",
         {"model": "BAAI/bge-m3", "input": ["ping"]},
         "NEBIUS_API_KEY"),
        # Together : la cle EST au coffre et la doc HF le classe en feature-extraction.
        # Sert-il `BAAI/bge-m3` ou seulement d'autres bge ? Une cle disponible et un
        # modele non teste, c'est une capacite INCONNUE -- pas une capacite absente.
        ("together", "https://api.together.xyz/v1/embeddings",
         {"model": "BAAI/bge-m3", "input": ["ping"]},
         "TOGETHER_API_KEY"),
        # DeepInfra sert bge-m3 (c'est l'un des fournisseurs d'OpenRouter pour ce
        # modele) et sa clef dormait au coffre sous le nom nu `DEEPINFRA`.
        ("deepinfra", "https://api.deepinfra.com/v1/openai/embeddings",
         {"model": "BAAI/bge-m3", "input": ["ping"]},
         "DEEPINFRA"),
    ]

    # MODAL A PART : son endpoint n'attend pas de cle en en-tete (l'URL EST le secret,
    # elle vient du coffre) et son contrat est `{texts: [...]}` -> `{embeddings: [...]}`.
    # Ajoute le 2026-09-06 parce que le bench rendait « KO » en 5,3 s sans jamais dire
    # POURQUOI : 404 workspace desactive, 401, 500 de l'app ou timeout de demarrage a
    # froid ne se traitent pas pareil, et un « KO » muet les confond tous.
    try:
        from nokido_agent.app.forge_secrets import get_secret as _gs2

        _murl = _gs2("LAFORGE_MODAL_EMBED_URL") or os.environ.get("LAFORGE_MODAL_EMBED_URL", "")
    except Exception as _e:  # noqa: BLE001
        _murl = ""
        print("  %-8s coffre illisible (%s)" % ("modal", type(_e).__name__))
    if not _murl:
        print("  %-8s AUCUNE url lisible au coffre" % "modal")
    else:
        import json as _jm
        import urllib.error as _ue
        import urllib.request as _um

        _req = _um.Request(_murl, data=_jm.dumps({"texts": ["ping"]}).encode(),
                           headers={"Content-Type": "application/json",
                                    "User-Agent": "Mozilla/5.0 LaForge-Embed"})
        try:
            # 90 s : un conteneur GPU qui demarre a froid peut depasser largement les
            # 20 s du chemin de production -- confondre « lent a demarrer » et « mort »
            # est exactement ce qu'on cherche a eviter ici.
            with _um.urlopen(_req, timeout=90.0) as _r:
                _d = _jm.loads(_r.read())
            _emb = _d.get("embeddings") or []
            print("  %-8s HTTP 200  n=%s dim=%s" % (
                "modal", len(_emb), (len(_emb[0]) if _emb and isinstance(_emb[0], list) else "?")))
        except _ue.HTTPError as _e:
            _corps = ""
            try:
                _corps = _e.read().decode("utf-8", "replace")[:220]
            except Exception:  # noqa: BLE001 - corps illisible, le code suffit
                pass
            print("  %-8s HTTP %s  %s" % ("modal", _e.code, _corps))
        except Exception as _e:  # noqa: BLE001
            print("  %-8s ERR %s: %s" % ("modal", type(_e).__name__, str(_e)[:200]))
    for nom, url, payload, envname in essais:
        try:
            from nokido_agent.app.forge_secrets import get_secret

            cle = None
            for cand in (envname, nom.upper() + "_API_KEY", nom.upper() + "_KEY"):
                try:
                    cle = get_secret(cand)
                except Exception:  # noqa: BLE001 - candidat suivant
                    cle = None
                if cle:
                    break
            if not cle:
                # SANS CLE, on qualifie quand meme la ROUTE : l'endpoint repond-il ?
                # C'est la difference entre « a ouvrir un compte » et « n'existe pas ».
                try:
                    _r0 = urllib.request.Request(
                        url, data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(_r0, timeout=20.0) as _rr:
                        print("  %-8s AUCUNE cle au coffre, mais HTTP %s SANS auth (!)"
                              % (nom, _rr.status))
                except urllib.error.HTTPError as _e0:
                    _dit = {401: "route VIVANTE, il ne manque qu'une cle",
                            403: "route vivante, acces refuse",
                            404: "route INEXISTANTE a cette adresse"}.get(
                                _e0.code, "a instruire")
                    print("  %-8s AUCUNE cle au coffre | HTTP %s -- %s"
                          % (nom, _e0.code, _dit))
                except Exception as _e0:  # noqa: BLE001
                    print("  %-8s AUCUNE cle au coffre | injoignable (%s) -- INDETERMINE"
                          % (nom, type(_e0).__name__))
                continue
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer %s" % cle})
            with urllib.request.urlopen(req, timeout=25.0) as r:
                d = json.loads(r.read())
            dim = len((d.get("data") or [{}])[0].get("embedding") or [])
            print("  %-8s HTTP 200  dim=%d" % (nom, dim))
        except urllib.error.HTTPError as e:
            corps = ""
            try:
                corps = e.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001 - corps illisible, le code suffit
                pass
            print("  %-8s HTTP %s  %s" % (nom, e.code, corps))
        except Exception as e:  # noqa: BLE001
            print("  %-8s ERR %s: %s" % (nom, type(e).__name__, str(e)[:160]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
