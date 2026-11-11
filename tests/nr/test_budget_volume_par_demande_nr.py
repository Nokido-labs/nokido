"""NR 5/11 (owner, tokens) : budget de volume par demande, git grep compte comme Grep, compactage sans renvoi."""
import json
import subprocess
import sys
from pathlib import Path

OUTILS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(OUTILS))

import forge_cmd_compactor as CC  # noqa: E402
import forge_recon_breaker as RB  # noqa: E402
import hook_context_firewall as FW  # noqa: E402
import hook_tool_budget_gate as G  # noqa: E402

MEMOIRE = "C:/Users/x/.claude/projects/p/memory/fiche.md"


def _demande(texte):
    return {"type": "user", "message": {"content": texte}}


def _appel(uid, nom, entree, taille):
    return [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": uid, "name": nom, "input": entree}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": "x" * taille}]}},
    ]


def _transcription(tmp_path, entrees):
    f = tmp_path / "t.jsonl"
    f.write_text("".join(json.dumps(e) + "\n" for e in entrees), encoding="utf-8")
    return str(f)


def _pre(transcription, nom="Read", entree=None):
    return {"hook_event_name": "PreToolUse", "tool_name": nom, "tool_input": entree or {"file_path": "a.py"},
            "transcript_path": transcription, "session_id": "s"}


def test_le_volume_repart_a_zero_a_chaque_demande_et_pas_sur_une_notification(tmp_path):
    t = _transcription(tmp_path, [
        _demande("une"), *_appel("a", "Read", {"file_path": "a"}, 900),
        _demande("deux"), *_appel("b", "Read", {"file_path": "b"}, 100),
        _demande("<task-notification>fin</task-notification>"), *_appel("c", "Read", {"file_path": "c"}, 100),
    ])
    assert G.volume_demande(t) == 200 + 2 * 2


def test_un_message_en_cours_de_tour_est_une_demande(tmp_path):
    t = _transcription(tmp_path, [
        _demande("une"), *_appel("a", "Read", {"file_path": "a"}, 900),
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "reprends"}},
        *_appel("b", "Read", {"file_path": "b"}, 100),
    ])
    assert G.volume_demande(t) == 100 + 2


def test_memoire_et_git_courant_hors_budget_mais_pas_les_lectures_git(tmp_path):
    t = _transcription(tmp_path, [
        _demande("une"),
        *_appel("m", "Read", {"file_path": MEMOIRE}, 5000),
        *_appel("s", "Bash", {"command": 'git -C "d" status --short'}, 5000),
        *_appel("c", "Bash", {"command": 'git commit -m "show diff grep"'}, 5000),
        *_appel("q", "AskUserQuestion", {}, 5000),
        *_appel("j", "mcp__nokido-oauth__run", {"action": "run_job"}, 5000),
        *_appel("g", "Bash", {"command": 'git -C "d" show HEAD'}, 100),
        *_appel("p", "Bash", {"command": "git log -p -1"}, 100),
    ])
    assert G.volume_demande(t) == 200 + 2 * 2


def test_la_reponse_a_une_question_remet_le_compteur_a_zero(tmp_path):
    t = _transcription(tmp_path, [
        _demande("une"), *_appel("a", "Read", {"file_path": "a"}, 900),
        *_appel("q", "AskUserQuestion", {}, 50),
        *_appel("b", "Read", {"file_path": "b"}, 100),
    ])
    assert G.volume_demande(t) == 100 + 2


def test_la_surveillance_d_un_job_reste_hors_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "500")
    t = _transcription(tmp_path, [_demande("une"), *_appel("a", "Read", {"file_path": "a"}, 600)])
    commande = '"C:/py/python.exe" "C:/d/tools/forge_job_watch_cli.py" --job job_x'
    assert G.verdict_volume(_pre(t), "Monitor", {"command": commande}) == (False, "")
    assert G.verdict_volume(_pre(t), "Bash", {"command": commande}) == (False, "")
    assert G.verdict_volume(_pre(t), "Bash", {"command": "ls"})[0] is True


def test_au_dela_du_plafond_le_point_d_entree_refuse(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "500")
    t = _transcription(tmp_path, [_demande("une"), *_appel("a", "Read", {"file_path": "a"}, 600)])
    monkeypatch.setenv("LAFORGE_BUDGET_DIR", str(tmp_path))
    monkeypatch.setattr(G, "DOSSIER_ETAT", tmp_path)
    assert G.traiter(_pre(t)) == 0
    sortie = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert sortie["permissionDecision"] == "deny" and "BUDGET_VOLUME" in sortie["permissionDecisionReason"]
    assert "job_status" in sortie["permissionDecisionReason"]


def test_un_collage_de_l_owner_remet_le_compteur_a_zero(tmp_path):
    """5/11 : `<pasted_content` ouvre le message, le compteur montait a 69 794 malgre deux demandes."""
    t = _transcription(tmp_path, [
        _demande("une"), *_appel("a", "Read", {"file_path": "a"}, 900),
        _demande('<pasted_content id="b52a">\nrefus\n</pasted_content id="b52a">\n\npourquoi ?'),
        *_appel("b", "Read", {"file_path": "b"}, 100),
    ])
    assert G.volume_demande(t) == 100 + 2


def test_une_commande_de_l_owner_compte_mais_pas_sa_sortie(tmp_path):
    t = _transcription(tmp_path, [
        _demande("une"), *_appel("a", "Read", {"file_path": "a"}, 900),
        _demande("<command-name>/context</command-name>"), *_appel("b", "Read", {"file_path": "b"}, 100),
        _demande("<local-command-stdout>sortie</local-command-stdout>"), *_appel("c", "Read", {"file_path": "c"}, 100),
    ])
    assert G.volume_demande(t) == 200 + 2 * 2


def test_le_resultat_d_un_deport_reste_lisible_au_dela_du_plafond(tmp_path, monkeypatch):
    """Le refus dit de deporter : refuser ensuite job_status rendait le resultat illisible."""
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "500")
    t = _transcription(tmp_path, [_demande("une"), *_appel("a", "Read", {"file_path": "a"}, 600)])
    run = "mcp__nokido-oauth__run"
    assert G.verdict_volume(_pre(t), run, {"action": "job_status", "job_id": "j"}) == (False, "")
    assert G.verdict_volume(_pre(t), run, {"action": "shell", "command": "ls"})[0] is True


def test_l_etat_du_budget_est_visible_avant_le_refus(tmp_path, capsys, monkeypatch):
    """Owner 5/11 : « pourquoi tu lances qqch qui va etre refuse ? »."""
    monkeypatch.setattr(G, "DOSSIER_ETAT", tmp_path)
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "1000")
    t = _transcription(tmp_path, [_demande("une"), *_appel("a", "Read", {"file_path": "a"}, 800)])
    assert G.traiter(_pre(t)) == 0
    sortie = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert "permissionDecision" not in sortie
    assert sortie["hookEventName"] == "PreToolUse"
    assert "[budget-volume] 802/1000" in sortie["additionalContext"]


def test_sous_le_seuil_d_etat_le_hook_se_tait(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(G, "DOSSIER_ETAT", tmp_path)
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "10000")
    t = _transcription(tmp_path, [_demande("une"), *_appel("a", "Read", {"file_path": "a"}, 800)])
    assert G.traiter(_pre(t)) == 0
    assert capsys.readouterr().out == ""


def test_hors_budget_et_interrupteur_laissent_passer(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(G, "DOSSIER_ETAT", tmp_path)
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "500")
    t = _transcription(tmp_path, [_demande("une"), *_appel("a", "Read", {"file_path": "a"}, 600)])
    assert G.verdict_volume(_pre(t), "Read", {"file_path": MEMOIRE}) == (False, "")
    assert G.verdict_volume(_pre(t), "Bash", {"command": "git status"}) == (False, "")
    assert G.verdict_volume(_pre(t), "Read", {"file_path": "a.py"})[0] is True
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "0")
    assert G.verdict_volume(_pre(t), "Read", {"file_path": "a.py"}) == (False, "")
    assert capsys.readouterr().out == ""


def test_git_grep_passe_par_le_disjoncteur_de_recon(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(G, "DOSSIER_ETAT", tmp_path)
    monkeypatch.setenv("LAFORGE_VOLUME_PLAFOND", "0")
    vus = []
    monkeypatch.setattr(RB, "verdict", lambda s, k, n: vus.append((s, k, n)) or ("deny", "recon plafonnee", 9))
    assert G.traiter(_pre("", "Bash", {"command": 'git -C "d" grep -n motif'})) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert vus == [("s", "search", True)]


def _garde_refuse(commande):
    """bash_guard par son point d'entree reel : il lit stdin et sort des l'import, il ne s'importe pas."""
    r = subprocess.run([sys.executable, str(OUTILS / "bash_guard.py")], capture_output=True, text=True,
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": commande}}),
                       encoding="utf-8", errors="replace", timeout=25, check=False)
    return "BLOCKED" in r.stdout + r.stderr


def test_bash_guard_ferme_la_lecture_git_vers_un_fichier():
    assert _garde_refuse('git -C "d" show HEAD:a.md > C:/tmp/a.md')
    assert _garde_refuse("git grep motif > f.txt")
    assert _garde_refuse("git log -p -1 > f.txt")
    # 2>&1 n'est pas une redirection vers un fichier ; --stat : un show nu est refuse depuis le levier (c) du 9/11.
    assert not _garde_refuse("git show --stat HEAD 2>&1")
    assert _garde_refuse("git show HEAD 2>&1")
    assert not _garde_refuse("git diff A B > C:/tmp/p.patch")  # voie d'integration par patch
    assert not _garde_refuse('git log --grep="a > b"')


def test_le_pare_feu_compacte_le_bash_sans_renvoi(capsys, monkeypatch):
    monkeypatch.setattr(CC, "load_filters", dict)
    monkeypatch.setattr(CC, "compact", lambda c, o, f: {"name": "t", "filtered": "court", "raw_chars": len(o), "kept_chars": 5})
    ev = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "git show HEAD"},
          "tool_output": "long " * 50, "tool_succeeded": True}
    assert FW.traiter(ev) == 0
    sortie = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedToolOutput"]
    assert sortie == {"text": "court", "isError": False}


def test_le_pare_feu_ne_touche_ni_un_echec_ni_une_mutation(capsys, monkeypatch):
    monkeypatch.setattr(CC, "compact", lambda c, o, f: (_ for _ in ()).throw(AssertionError("ne doit pas compacter")))
    for cmd, ok in (("git show HEAD", False), ("git commit -m x", True), ("git show HEAD | head", True)):
        ev = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
              "tool_output": "long " * 50, "tool_succeeded": ok}
        assert FW.traiter(ev) == 0
    assert capsys.readouterr().out == ""


# Formes MESUREES le 5/11 par sonde dans le hook vivant : ni `tool_output` ni `tool_succeeded`.
# Les tests ci-dessus nourrissaient une forme que le runtime n'envoie pas : verts sur un hook inerte.
def _bash_reel(cmd, stdout, stderr=""):
    return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
            "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False,
                              "isImage": False, "noOutputExpected": False}}


def test_forme_reelle_le_bash_est_compacte(capsys, monkeypatch):
    monkeypatch.setattr(CC, "load_filters", dict)
    monkeypatch.setattr(CC, "compact", lambda c, o, f: {"name": "t", "filtered": "court", "raw_chars": len(o), "kept_chars": 5})
    assert FW.traiter(_bash_reel("git show HEAD", "long " * 50)) == 0
    sortie = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedToolOutput"]
    # Forme CONSTATEE sur le runtime le 5/11 ; {"text", "isError"} est ignoree sans erreur.
    assert sortie["stdout"] == "court" and sortie["stderr"] == "" and sortie["interrupted"] is False
    assert "text" not in sortie


def test_forme_reelle_le_stderr_compte_dans_la_sortie(capsys, monkeypatch):
    vu = {}
    monkeypatch.setattr(CC, "load_filters", dict)
    monkeypatch.setattr(CC, "compact", lambda c, o, f: vu.update(o=o) or {"name": None, "raw_chars": 1, "kept_chars": 1})
    FW.traiter(_bash_reel("git show HEAD", "SORTIE", "ALERTE"))
    assert "SORTIE" in vu["o"] and "ALERTE" in vu["o"]


def test_forme_reelle_le_mcp_volumineux_est_reduit(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(FW, "DOSSIER_ARCHIVE", tmp_path)
    ev = {"hook_event_name": "PostToolUse", "tool_name": "mcp__nokido-oauth__run",
          "tool_response": [{"type": "text", "text": "ok\n" * 20000}]}
    assert FW.traiter(ev) == 0
    blocs = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedMCPToolOutput"]
    assert blocs[0]["type"] == "text" and "context-firewall" in blocs[0]["text"]


def test_le_hook_lit_son_entree_en_utf8_meme_sous_une_locale_windows(capsys, monkeypatch, tmp_path):
    # Paye le 5/11 : stdin Windows en cp1252 -> "Débat" rendu "DÃ©bat" dans toute sortie reecrite.
    import io
    monkeypatch.setattr(FW, "DOSSIER_ARCHIVE", tmp_path)
    ev = _bash_reel("git log -100", "Débat évité\n" * 2000)
    brut = json.dumps(ev, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(FW.sys, "stdin", io.TextIOWrapper(io.BytesIO(brut), encoding="cp1252"))
    monkeypatch.setattr(CC, "load_filters", dict)
    assert FW.main() == 0
    rendu = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
    assert "Débat évité" in rendu and "Ã" not in rendu


def test_un_contenu_demande_nest_jamais_ampute(capsys, tmp_path, monkeypatch):
    # Paye le 5/11 : `git show <rev>:<doc>` reduit de 111 a 37 lignes, les conclusions du document perdues.
    monkeypatch.setattr(FW, "DOSSIER_ARCHIVE", tmp_path)
    for cmd in ('git -C "C:/a b/Nokido" show a407348ca:docs/enquetes/x.md', "git show HEAD~1:app/x.py",
                'git -C "C:/a b" diff A B'):
        assert FW.traiter(_bash_reel(cmd, "ligne de contenu\n" * 3000)) == 0
    assert "ToolOutput" not in capsys.readouterr().out


def test_le_bandeau_donne_le_chemin_complet_de_lintegral(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(FW, "DOSSIER_ARCHIVE", tmp_path)
    assert FW.traiter(_bash_reel("forge_outil --journal", "ok\n" * 20000)) == 0
    assert str(tmp_path) in json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedToolOutput"]["stdout"]


def test_usage_reel_une_reponse_en_flux_ne_compte_quune_fois():
    import forge_contexte_par_source as CPS
    u1 = {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100, "output_tokens": 2}
    u2 = dict(u1, output_tokens=50)
    r = CPS.usage_reel([{"message": {"id": "a", "usage": u1}}, {"message": {"id": "a", "usage": u2}},
                        {"message": {"id": "b", "usage": u1}}, {"type": "autre"}])
    assert r["reponses"] == 2 and r["output_tokens"] == 52 and r["cache_read_input_tokens"] == 200


def test_simulation_de_plafond_rejoue_les_increments():
    import forge_contexte_par_source as CPS
    entrees = [{"message": {"id": str(i), "usage": {"cache_read_input_tokens": c}}} for i, c in enumerate((100, 200, 300, 400))]
    r = CPS.simuler_plafond(entrees, plafond=250, reprise=50)
    # 50, 150, 250, puis 350 > 250 : retour a 50.
    assert (r["reel"], r["simule"], r["reprises"]) == (1000, 500, 1)
    assert CPS.simuler_plafond(entrees, plafond=10**6, reprise=50)["reprises"] == 0


def test_relectures_apres_compaction_comptees_par_cesure():
    import forge_contexte_par_source as CPS

    def lecture(i, chemin):
        return {"message": {"content": [{"type": "tool_use", "id": i, "name": "Read", "input": {"file_path": chemin}}]}}

    def retour(i, texte):
        return {"message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": texte}]}}

    entrees = [lecture("a", "C:\\X\\A.py"), retour("a", "aaaa"), lecture("b", "c:/x/b.py"), retour("b", "bb"),
               {"type": "system", "subtype": "compact_boundary"},
               lecture("c", "c:/x/a.py"), retour("c", "aaaaaa"), lecture("d", "c:/x/neuf.py"), retour("d", "n")]
    assert CPS.relectures_apres_compaction(entrees) == [{"lus_avant": 2, "relus": 1, "car_relus": 6, "appels": 2}]


def test_forme_inconnue_ou_bloc_non_texte_rien_ne_change(capsys):
    for reponse in ([{"type": "image", "data": "x" * 200000}], {"autre": "x" * 200000}, 12, None):
        ev = {"hook_event_name": "PostToolUse", "tool_name": "mcp__nokido-oauth__run", "tool_response": reponse}
        assert FW.traiter(ev) == 0
    assert "ToolOutput" not in capsys.readouterr().out
