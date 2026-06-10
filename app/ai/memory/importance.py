"""Memory importance scoring — not all memories are equal."""


class MemoryImportanceScorer:
    """Deterministic importance for long-term memory retention and ranking."""

    def score_preference(self, *, count: int, recurring: bool = True) -> float:
        base = 0.55 if recurring else 0.4
        return min(1.0, base + count * 0.04)

    def score_workflow_fact(self, *, pending: bool = False) -> float:
        return 0.85 if pending else 0.6

    def score_graph_link(self, *, usage_count: int = 1) -> float:
        return min(0.9, 0.5 + usage_count * 0.05)

    def score_ephemeral_chat(self) -> float:
        return 0.15

    def should_decay(self, importance: float, *, threshold: float = 0.25) -> bool:
        return importance < threshold
