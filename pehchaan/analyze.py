"""Batch analysis job: run the identity-graph ring analysis and (if ground truth exists)
measure matching accuracy. Works on whatever database PEHCHAAN_DB_URL points to.

Usage:
    python -m pehchaan.analyze
"""
import json
import logging
from datetime import datetime, timezone

from pehchaan.config import DATA_DIR
from pehchaan.evaluate import load_ground_truth, pairwise_metrics
from pehchaan.rings import analyze_rings, evaluate_rings
from pehchaan.store import Store

log = logging.getLogger(__name__)


def run_analysis(store: Store) -> dict:
    report = analyze_rings(store.current_identity_attributes())
    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S")
    store.save_ring_report(run_id, report, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    summary = {"run_id": run_id, "stats": store.stats(), "components_reported": len(report)}

    truth_path = DATA_DIR / "ground_truth.csv"
    if truth_path.exists():
        truth = load_ground_truth(truth_path)
        predicted = store.current_assignments()
        summary["matching_accuracy"] = pairwise_metrics(predicted, truth)
        summary["ring_detection"] = evaluate_rings(report, predicted, truth)
    summary["top_suspicious"] = [
        {k: r[k] for k in ("component_id", "label", "risk_score", "reasons", "features")}
        for r in report if r["label"] == "SUSPICIOUS_RING"][:3]
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store()
    store.init_schema()
    print(json.dumps(run_analysis(store), indent=2, default=str))
    store.close()


if __name__ == "__main__":
    main()
