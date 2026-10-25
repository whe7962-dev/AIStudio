from aiside.core.project_graph import DIRTY, DONE, ProjectGraph


def test_add_and_downstream():
    g = ProjectGraph("p1")
    a = g.add_node("ingest")
    b = g.add_node("anchor", upstream=[a.id])
    c = g.add_node("generate", upstream=[b.id])
    assert g.downstream(a.id) == {a.id, b.id, c.id}
    assert g.upstream(c.id) == {b.id}


def test_incremental_recompute_only_downstream():
    g = ProjectGraph("p1")
    a = g.add_node("ingest")
    b = g.add_node("anchor", upstream=[a.id])
    c = g.add_node("generate", upstream=[b.id])
    d = g.add_node("export", upstream=[c.id])
    # 全部置为 done
    for nid in (a.id, b.id, c.id, d.id):
        g.set_status(nid, DONE)

    affected = g.update_params(b.id, {"x": 1})
    assert affected == {b.id, c.id, d.id}
    assert g.nodes[a.id].status == DONE          # 上游不动
    assert g.nodes[b.id].status == DIRTY
    assert g.nodes[c.id].status == DIRTY
    assert g.nodes[d.id].status == DIRTY


def test_anchor_change_invalidates_downstream_only():
    g = ProjectGraph("p1")
    a = g.add_node("ingest")
    b = g.add_node("anchor", upstream=[a.id])
    c = g.add_node("generate", upstream=[b.id])
    g.set_status(b.id, DONE)
    affected = g.invalidate_downstream(b.id)
    assert affected == {c.id}
    assert g.nodes[b.id].status == DONE
    assert g.nodes[c.id].status == DIRTY


def test_remove_node():
    g = ProjectGraph("p1")
    a = g.add_node("ingest")
    b = g.add_node("anchor", upstream=[a.id])
    c = g.add_node("generate", upstream=[b.id])
    affected = g.remove_node(b.id)
    assert affected == {b.id, c.id}
    assert b.id not in g.nodes and c.id not in g.nodes
    assert a.id in g.nodes


def test_topological_order_and_cycle():
    g = ProjectGraph("p1")
    a = g.add_node("a")
    b = g.add_node("b", upstream=[a.id])
    c = g.add_node("c", upstream=[b.id])
    assert g.topological_order() == [a.id, b.id, c.id]
    # 造环
    g.connect(c.id, a.id)
    try:
        g.topological_order()
        assert False, "应当检测到环"
    except ValueError:
        pass


def test_undo_and_persistence(tmp_path):
    g = ProjectGraph("p1")
    a = g.add_node("ingest")
    g.update_params(a.id, {"x": 1})
    assert a.id in g.nodes
    g.undo()
    assert a.id in g.nodes  # undo 恢复到 add 之后、update 之前

    path = tmp_path / "project.json"
    g.save(path)
    loaded = ProjectGraph.load(path)
    assert loaded.project_id == g.project_id
    assert set(loaded.nodes) == set(g.nodes)


def test_generation_cache_key():
    k1 = ProjectGraph.generation_cache_key("p", 1, "m", "a")
    k2 = ProjectGraph.generation_cache_key("p", 1, "m", "a")
    k3 = ProjectGraph.generation_cache_key("p", 2, "m", "a")
    assert k1 == k2 and k1 != k3
