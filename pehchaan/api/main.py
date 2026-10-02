"""Pehchaan REST API + analyst console.

Run:      uvicorn pehchaan.api.main:app --reload
Console:  http://localhost:8000/          (redirects to /ui/)
API docs: http://localhost:8000/docs      (interactive Swagger UI, generated automatically)
"""
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pehchaan.api import service
from pehchaan.store import Store

app = FastAPI(
    title="Pehchaan Identity API",
    description="Point-in-time identity resolution with explanations, plus an analyst review console at /ui/.",
    version="0.2.0",
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

AS_OF = Query(None, description="ISO date/time, e.g. 2026-03-01. Omit for the current view.",
              examples=["2026-03-01"])


class ReviewIn(BaseModel):
    decision: Literal["confirmed_fraud", "false_alarm"]
    note: str = Field("", max_length=500)


def get_store() -> Iterator[Store]:
    """One database connection per request, always closed afterwards."""
    store = Store()
    try:
        yield store
    finally:
        store.close()


def call(fn, *args, **kwargs):
    """Translate service errors into HTTP status codes."""
    try:
        return fn(*args, **kwargs)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.BadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")


@app.get("/health")
def health(store: Store = Depends(get_store)):
    try:
        store.query("SELECT 1 AS ok")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")


@app.get("/stats")
def stats(store: Store = Depends(get_store)):
    return store.stats()


@app.get("/overview")
def overview(store: Store = Depends(get_store)):
    """Counts for the console's front page: records, identities, review queue."""
    return service.overview(store)


@app.get("/activity")
def activity(limit: int = Query(15, ge=1, le=100), store: Store = Depends(get_store)):
    """Latest records and merges, newest first."""
    return service.activity(store, limit)


@app.get("/identities/{identity_id}")
def get_identity(identity_id: str, as_of: str | None = AS_OF, store: Store = Depends(get_store)):
    """Every record we believe belongs to this person, now or at a past moment."""
    return call(service.identity_view, store, identity_id, as_of)


@app.get("/identities/{identity_id}/history")
def get_history(identity_id: str, store: Store = Depends(get_store)):
    """When each record joined or left this identity, and why."""
    return call(service.history_view, store, identity_id)


@app.get("/identities/{identity_id}/explain")
def explain(identity_id: str, store: Store = Depends(get_store)):
    """The evidence behind every link that holds this identity together."""
    return call(service.explain_view, store, identity_id)


@app.get("/records/{record_id}")
def get_record(record_id: str, as_of: str | None = AS_OF, store: Store = Depends(get_store)):
    """Which identity this record belongs to, now or at a past moment."""
    return call(service.record_view, store, record_id, as_of)


@app.get("/search")
def search(q: str | None = Query(None, description="Name, phone or email; detected automatically"),
           phone: str | None = None, email: str | None = None, name: str | None = None,
           store: Store = Depends(get_store)):
    """Find identities. Name search is phonetic: 'Lakshmi' also finds 'Laxmi'."""
    if q is not None:
        return call(service.smart_search, store, q)
    return call(service.search, store, phone, email, name)


@app.get("/rings")
def rings(label: str | None = Query(None, description="SUSPICIOUS_RING, REVIEW or LIKELY_FAMILY"),
          store: Store = Depends(get_store)):
    """Latest identity-graph analysis: connected groups scored as family vs fraud ring."""
    return call(service.rings_view, store, label)


@app.get("/rings/{run_id}/{component_id}")
def ring_detail(run_id: str, component_id: int, store: Store = Depends(get_store)):
    """One group with its graph: identities as nodes, shared phones/devices/addresses as edges."""
    return call(service.ring_detail, store, run_id, component_id)


@app.post("/rings/{run_id}/{component_id}/review")
def review_ring(run_id: str, component_id: int, body: ReviewIn, store: Store = Depends(get_store)):
    """Record an analyst's decision on a group."""
    return call(service.review_ring, store, run_id, component_id, body.decision, body.note)
