"""Model table: provider, display name and API prices of every model the LLM Baseline may call.

The LLM Baseline computes each run's cost from its token usage and this table (SPEC section 10.2):
cost = input tokens x input price + output tokens x output price, prices in USD per million
tokens. A model missing from the table cannot run in real mode (its per-run cost cap could not be
enforced): add a row here first. ``stableagent run --estimate`` and the dashboard's cost
preview use the same prices.

Prices are list prices for standard (non-batch, non-cached) requests, checked on the date given.
"""
from __future__ import annotations

from dataclasses import dataclass

ANTHROPIC = "anthropic"
OPENAI = "openai"
PROVIDERS = (ANTHROPIC, OPENAI)


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    display_name: str  # e.g. "Claude Sonnet 4.6": the dashboard, the figure, the tables
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    checked: str  # when the prices were last checked against the provider's price list

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok
        ) / 1_000_000


MODELS: dict[str, ModelInfo] = {
    "claude-sonnet-4-6": ModelInfo(ANTHROPIC, "Claude Sonnet 4.6", 3.00, 15.00, "2026-10"),
    "claude-haiku-4-5-20251001": ModelInfo(ANTHROPIC, "Claude Haiku 4.5", 1.00, 5.00, "2026-10"),
    "gpt-4o": ModelInfo(OPENAI, "GPT-4o", 2.50, 10.00, "2026-10"),
}


class UnknownModelError(KeyError):
    """The model is not in the model table, so the cost of its runs cannot be computed."""

    def __str__(self) -> str:  # KeyError would print the message quoted
        return str(self.args[0]) if self.args else ""


def model_info(model: str) -> ModelInfo:
    """The table row of ``model``; UnknownModelError, naming the known models, if it has none."""
    info = MODELS.get(model)
    if info is None:
        raise UnknownModelError(
            f"Model '{model}' has no price in the model table "
            f"(stableagent/config/pricing.py; known: {', '.join(sorted(MODELS))}), so the "
            "cost of its runs and the per-run cost cap cannot be computed. Add it there first."
        )
    return info


def display_name(model: str) -> str:
    """The model's display name, else its id."""
    info = MODELS.get(model)
    return info.display_name if info else model
