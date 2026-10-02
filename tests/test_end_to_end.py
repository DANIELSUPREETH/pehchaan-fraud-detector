"""Generate a small dataset, resolve it, and check accuracy and ring detection."""
from pehchaan.contracts import to_canonical
from pehchaan.evaluate import pairwise_metrics
from pehchaan.generator.generate import Generator
from pehchaan.resolver import Resolver
from pehchaan.rings import analyze_rings, evaluate_rings
from pehchaan.store import Store


def test_pipeline_accuracy_on_synthetic_data():
    gen = Generator(seed=7)
    gen.run(n_persons=600, n_rings=5)
    store = Store("sqlite:///:memory:")
    store.init_schema()
    resolver = Resolver(store)
    for envelope in gen.records:
        resolver.process(to_canonical(envelope))
    store.commit()

    truth = {t["record_id"]: t for t in gen.truth}
    predicted = store.current_assignments()
    metrics = pairwise_metrics(predicted, truth)
    assert metrics["precision"] >= 0.95, metrics
    assert metrics["recall"] >= 0.85, metrics

    report = analyze_rings(store.current_identity_attributes())
    rings = evaluate_rings(report, predicted, truth)
    assert rings["rings_flagged"] >= 3, rings
    assert rings["families_falsely_flagged"] == 0, rings
