"""tools/patch_notify_reveille_drain.py — le courrier REVEILLE son drain.

Defaut mesure le 31-07. La chaine M2M vers AGY autonome est complete et SAINE
(prouve : post -> queued -> delivered en 1,1 s -> acked par GEMINI -> reponse
correlee par in_reply_to). Elle ne marche pourtant QUE si quelqu'un a reveille
`NokidoGeminiAutonomous` a la main : le service est `disabled = true` depuis le
2026-06-18, par decision owner assumee (son tick entre en contention avec les CLI
interactifs). Son propre commentaire dit « reveil via nokido_ensure_service au
besoin » — et PERSONNE ne l'appelait.

C'est un garde sans emetteur, a l'envers : la capacite de reveil existe, aucun
chemin ne la declenche. Consequence : tout notify vers AGY pendant que le drain
dort reste `delivered` sans jamais etre traite, sans que rien ne le signale. C'est
la cause des « reponses perdues » cote postal, distincte de la fausse completion
cote tasks.db (corrigee par 153504ce).

CE QUE FAIT CE PATCH : apres le depot postal gouverne (post + facteur), si le
destinataire est AGY, on s'assure que son drain tourne. Le message EST l'intention
— meme doctrine que les cerveaux souverains a la demande.

CE QU'IL NE FAIT PAS : il ne passe PAS le service a disabled=false. La decision
owner du 18-06 (pas de tick permanent pendant les sessions interactives) reste
intacte ; on reveille a la demande, on n'installe pas une boucle.

GARDES : reveil au plus une fois par 60 s (un flot de messages ne doit pas
marteler le superviseur) ; thread daemon pour ne JAMAIS bloquer l'event loop du
hub (un ensure_service fait des appels HTTP) ; echec journalise, jamais fatal —
le courrier est deja depose, le reveil est un bonus.

Pourquoi un patcher : app/forge_mcp_registry.py est CRITICAL_FILE, governed_edit
le refuse ; chemin officiel = patcher committe + run action=trusted_script.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ANCIEN = """                _pm = _postal_post(agent, _explicit_to, msg, reply_to=agent)
                _postal_facteur(_pm.get("recipient_channel", ""))
            except Exception:
                pass
"""

NOUVEAU = '''                _pm = _postal_post(agent, _explicit_to, msg, reply_to=agent)
                _postal_facteur(_pm.get("recipient_channel", ""))
                # LE COURRIER REVEILLE SON DRAIN (2026-07-31). NokidoGeminiAutonomous
                # est volontairement `disabled` (son tick concurrence les CLI
                # interactifs, decision owner du 18-06) et son commentaire prevoit
                # « reveil via nokido_ensure_service au besoin » — que personne
                # n'appelait. Un message livre a un drain endormi reste `delivered`
                # pour toujours, sans que rien ne le signale. Le message EST
                # l'intention : meme doctrine que les cerveaux a la demande.
                # On ne passe PAS le service en permanent : on le reveille.
                _dest_l = str(_explicit_to).strip().lower()
                if _dest_l in ("gemini", "agy", "antigravity"):
                    import threading as _th_w
                    import time as _t_w

                    _last = getattr(self, "_dernier_reveil_agy", 0.0)
                    if _t_w.time() - _last > 60.0:
                        self._dernier_reveil_agy = _t_w.time()

                        def _reveiller_drain():
                            # Thread daemon : ensure_service fait des appels HTTP au
                            # superviseur, jamais dans l'event loop du hub (wedge).
                            try:
                                import sys as _s_w

                                _s_w.path.insert(0, str(self.root / "tools"))
                                from forge_ensure_service import ensure as _ens

                                # Nom COMPLET : ensure() n'accepte qu'un alias de
                                # SVC_MAP ou un nom prefixe Nokido — un alias court
                                # inconnu rendrait « service inconnu » et le reveil
                                # aurait echoue en silence.
                                _r = _ens("NokidoGeminiAutonomous", "running")
                                logger.info(f"[postal] drain AGY reveille: {_r}")
                            except Exception as _we:  # noqa: BLE001
                                # Journalise : un reveil muet qui echoue redonne
                                # exactement la panne qu'on corrige ici.
                                logger.warning(
                                    f"[postal] reveil du drain AGY impossible "
                                    f"({type(_we).__name__}: {str(_we)[:120]}) — "
                                    f"le courrier est depose mais peut dormir")

                        _th_w.Thread(target=_reveiller_drain, daemon=True).start()
            except Exception:
                pass
'''


def main() -> int:
    p = ROOT / "app" / "forge_mcp_registry.py"
    src = p.read_text(encoding="utf-8")
    if "LE COURRIER REVEILLE SON DRAIN" in src:
        print("SKIP : patch deja applique")
        return 0
    n = src.count(ANCIEN)
    if n != 1:
        raise AssertionError(f"point d'ancrage non unique ({n} occurrences) — patch NON applique")
    src = src.replace(ANCIEN, NOUVEAU)
    ast.parse(src)  # AST valide AVANT d'ecrire (anti fail-close reboot)
    p.write_text(src, encoding="utf-8")
    relu = p.read_text(encoding="utf-8")
    if "LE COURRIER REVEILLE SON DRAIN" not in relu:
        raise AssertionError("RELECTURE sans le patch — edition perdue")
    print("PATCH APPLIQUE — verifie par relecture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
