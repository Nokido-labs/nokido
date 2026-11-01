"""Le garde de corrigibilite REFUSE (ILLISIBLE) quand la base du kill-switch ne peut pas etre lue : UNKNOWN != NO.

25/10 (CI de reference 50221f9ca) : une premiere livraison creait le dossier de la base a l'import -- une base vide
se lisait alors « kill-switch inactif » et laissait passer les outils mutants. Ce test fige le contraire. Le
kill-switch se lit chez forge_opsec, dont la base est resolue A CHAQUE APPEL par forge_db_path.authority_path() :
c'est elle qu'on rend absente (patcher forge_corrigibility.DB ne la touche pas).
"""


def test_corrigibility_illisible(tmp_path, monkeypatch):
    import nokido_agent.app.forge_corrigibility as corr
    import nokido_agent.app.forge_db_path as dbp

    absente = tmp_path / "absent" / "embeddings.db"   # dossier inexistant : sqlite ne peut pas l'ouvrir
    monkeypatch.setattr(dbp, "authority_path", lambda *a, **k: str(absente))
    allow, reason = corr.corrigibility_gate("run", "test", 2)
    assert not allow, reason
    assert "ILLISIBLE" in reason, reason
    assert not absente.parent.exists(), "le garde ne doit jamais fabriquer sa base"
