"""NR : un `POST /supervisor/service/stop/<nom>` ne doit pas etre suivi d'une relance par le superviseur lui-meme.

Mesure du 30/10 (laforge-master.log 02 h 07-02 h 09) : apres chaque stop du keeper, « NokidoLlamaEmbed: exited code=1
after 31s (restart #22) » puis « restart in 2000ms (attempt 23) » -- 25 redemarrages, QUICK-FAIL QUARANTINE, puis
relance a la levee. Cause : la route stop posait `state.status = "stopped"` APRES `await arreterVraiment(...)` ; pendant
l'attente, le gestionnaire de sortie (`if (state.status !== "sleeping" && state.status !== "stopped") scheduleRestart`)
lisait encore « running ». L'intention d'arret doit etre posee AVANT de tuer (REQUESTED avant ACHIEVED) ; le cas
SURVIT remet « running ».
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8")


def _route_stop() -> str:
    debut = SRC.index('if (p.startsWith("/supervisor/service/stop/") && req.method === "POST")')
    fin = SRC.index("\n  }\n", SRC.index("const held = !!state.proc;", debut))
    return SRC[debut:fin]


def test_l_intention_d_arret_est_posee_avant_de_tuer():
    route = _route_stop()
    tuer = route.index("await arreterVraiment(")
    poses = [m.start() for m in re.finditer(r'state\.status = "stopped";', route)]
    # le premier « stopped » est celui du service on-demand non instancie (retour anticipe) ; il en faut un AVANT tuer
    apres_held = route.index("const held = !!state.proc;")
    assert any(apres_held < p < tuer for p in poses), "stop pose 'stopped' apres l'arret : la sortie est relancee"


def test_un_arret_refuse_remet_running():
    route = _route_stop()
    survit = route[route.index('if (arretRes === "SURVIT")'):]
    bloc = survit[:survit.index("return jsonResp(")]
    assert 'state.status = "running";' in bloc


def test_le_gestionnaire_de_sortie_respecte_stopped():
    assert 'if (state.status !== "sleeping" && state.status !== "stopped") {' in SRC
