from __future__ import annotations


class OutputSimilarity:
    """Metric D — Output Similarity.

    Measures semantic similarity of the agent's full output (explanation +
    patch) across transformation variants, using embedding-based or BM25
    similarity.
    """

    def compute(self, run_data: list[dict]) -> None:
        # Deferred to future work
        return None
