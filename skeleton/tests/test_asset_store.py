from aiside.core.asset_store import AssetStore


def test_put_dedupe_and_get(tmp_path):
    store = AssetStore(tmp_path / "assets")
    cid1 = store.put(b"hello", {"kind": "text"})
    cid2 = store.put(b"hello", {"kind": "text"})
    assert cid1 == cid2
    assert store.get(cid1) == b"hello"
    assert store.exists(cid1)
    assert store.meta(cid1)["kind"] == "text"


def test_archive_then_purge(tmp_path):
    store = AssetStore(tmp_path / "assets")
    cid = store.put(b"data")
    store.archive(cid)
    assert store.meta(cid)["archived"] is True
    store.purge(cid)
    assert not store.exists(cid)


def test_missing_raises(tmp_path):
    store = AssetStore(tmp_path / "assets")
    try:
        store.get("missing")
        assert False
    except KeyError:
        pass
