import forge_ast_index as atlas


def test_get_index_returns_non_empty_dict():
    idx = atlas.get_index()
    assert isinstance(idx, dict) and idx["n_files"] > 0
    assert "imports_from" in idx and "imported_by" in idx


def test_ego_existing_file_returns_ok():
    res = atlas.ego("app/forge_handoff.py", 1)
    assert res["ok"] is True
    assert res["center"] == "app/forge_handoff.py"
    assert isinstance(res["calls_top"], list)
    assert isinstance(res["imports_from"], list)


def test_ego_unknown_file_returns_ok_false():
    res = atlas.ego("app/does_not_exist_xyz.py", 1)
    assert res["ok"] is False and "error" in res
