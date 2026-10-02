"""HTTP-level tests through FastAPI's TestClient. Skipped automatically if FastAPI isn't installed."""
import threading

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from pehchaan.api import main  # noqa: E402
from pehchaan.resolver import Resolver  # noqa: E402
from pehchaan.rings import analyze_rings  # noqa: E402
from pehchaan.store import Store  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    store = Store(url)
    store.init_schema()
    r = Resolver(store)
    for i, name in enumerate(["Arun Das", "Neha Joshi", "Imran Khan", "Ritu Verma"]):
        r.process({"record_id": f"EC-{i}", "source": "ecommerce", "ingested_at": f"2026-03-0{i + 1}T00:00:00",
                   "name": name, "phones": [f"70199{i}2331"], "device_id": "dev_shared"})
    store.commit()
    store.save_ring_report("run-1", analyze_rings(store.current_identity_attributes()), "2026-07-01T00:00:00")
    store.close()

    def test_store():  # a fresh connection per request, like the real dependency
        s = Store(url)
        try:
            yield s
        finally:
            s.close()

    main.app.dependency_overrides[main.get_store] = test_store
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_root_redirects_to_console(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code in (302, 307) and res.headers["location"] == "/ui/"
    page = client.get("/ui/")
    assert page.status_code == 200 and "Pehchaan" in page.text


def test_sqlite_store_works_across_threads(tmp_path):
    url = f"sqlite:///{tmp_path / 'threading.db'}"
    store = Store(url)
    store.init_schema()
    errors = []

    def worker():
        try:
            assert store.query("SELECT 1 AS ok") == [{"ok": 1}]
        except Exception as exc:  # pragma: no cover - captured for assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    store.close()


def test_overview_and_search(client):
    assert client.get("/overview").json()["stats"]["records"] == 4
    assert client.get("/search", params={"q": "neha joshi"}).json()["searched_as"] == "name"
    assert client.get("/search", params={"q": "  "}).status_code == 400


def test_review_round_trip(client):
    cid = client.get("/rings").json()["components"][0]["component_id"]
    assert client.get(f"/rings/run-1/{cid}").json()["nodes"]
    ok = client.post(f"/rings/run-1/{cid}/review", json={"decision": "confirmed_fraud", "note": "shared device"})
    assert ok.status_code == 200
    assert client.get("/rings").json()["components"][0]["review"]["decision"] == "confirmed_fraud"
    bad = client.post(f"/rings/run-1/{cid}/review", json={"decision": "maybe"})
    assert bad.status_code == 422  # rejected by the pydantic model before reaching our code


def test_unknown_identity_is_404(client):
    assert client.get("/identities/PID9999999").status_code == 404
