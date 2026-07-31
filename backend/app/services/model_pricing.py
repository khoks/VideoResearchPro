"""Model pricing table — E-1.13 cost calculator.

Rates in USD per 1M tokens, researched 2026-07-29 from the official
pricing pages (source URLs in docs/decisions.md D-054):

- OpenAI:    https://developers.openai.com/api/docs/pricing
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
- Google:    https://ai.google.dev/gemini-api/docs/pricing (page dated 2026-07-21)

Notes captured as data so the UI can surface them:
- OpenAI gpt-5.4 / gpt-5.5 double their rates above 272K input tokens
  per request (`long_context_*` fields; threshold 272,000). Our report
  batches cap at 120K so the standard tier applies in practice.
- claude-sonnet-5 is on INTRO pricing ($2/$10) through 2026-08-31;
  standard $3/$15 thereafter (note field).
- Gemini output rates INCLUDE thinking tokens; gemini-3.1-pro-preview
  and gemini-2.5-pro tier at 200K input (long_context fields).

Prices change; re-run the pricing research and update this table (the
`as_of` stamp is surfaced in the settings UI).
"""
from dataclasses import dataclass, field

PRICING_AS_OF = "2026-07-30"


@dataclass(frozen=True)
class ModelPricing:
    input_per_m: float
    output_per_m: float
    long_context_threshold: int | None = None
    long_context_input_per_m: float | None = None
    long_context_output_per_m: float | None = None
    note: str = ""


MODEL_PRICING: dict[str, ModelPricing] = {
    # --- OpenAI -----------------------------------------------------------
    "gpt-5.4": ModelPricing(2.50, 15.00, 272_000, 5.00, 22.50),
    "gpt-5.4-mini": ModelPricing(0.75, 4.50),
    "gpt-5.4-nano": ModelPricing(0.20, 1.25),
    "gpt-5.5": ModelPricing(5.00, 30.00, 272_000, 10.00, 45.00),
    "gpt-5.5-pro": ModelPricing(30.00, 180.00, note="no >272K tier published"),
    # 2026-07-30: OpenAI cut Luna 80% and Terra 20% (verified on the official
    # pricing page, not the announcement). Luna now matches gpt-5.4-nano on
    # input and undercuts it on output.
    "gpt-5.6-luna": ModelPricing(0.20, 1.20, 272_000, 0.40, 1.80),
    "gpt-5.6-sol": ModelPricing(5.00, 30.00, 272_000, 10.00, 45.00),
    "gpt-5.6-terra": ModelPricing(2.00, 12.00, 272_000, 4.00, 18.00),
    "gpt-4.1-mini": ModelPricing(0.40, 1.60),
    # --- Anthropic --------------------------------------------------------
    "claude-fable-5": ModelPricing(10.00, 50.00),
    "claude-opus-5": ModelPricing(5.00, 25.00),
    "claude-sonnet-5": ModelPricing(
        2.00, 10.00, note="intro pricing through 2026-08-31; then $3/$15"
    ),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
    # --- Google -----------------------------------------------------------
    "gemini-3.6-flash": ModelPricing(1.50, 7.50, note="output includes thinking; thinks by default — pin low effort"),
    "gemini-3.5-flash": ModelPricing(1.50, 9.00, note="output includes thinking"),
    "gemini-3.5-flash-lite": ModelPricing(0.30, 2.50),
    "gemini-3.1-pro-preview": ModelPricing(2.00, 12.00, 200_000, 4.00, 18.00, note="requires paid billing (active on this deployment since 2026-07-29)"),
    "gemini-3.1-flash-lite": ModelPricing(0.25, 1.50),
    "gemini-2.5-pro": ModelPricing(1.25, 10.00, 200_000, 2.50, 15.00, note="requires paid billing (active on this deployment since 2026-07-29)"),
    "gemini-2.5-flash": ModelPricing(0.30, 2.50),
    "gemini-2.5-flash-lite": ModelPricing(0.10, 0.40),
}

# Whisper audio transcription, $ per minute (used by ingest-cost hints).
WHISPER_PER_MINUTE = 0.006


def pricing_for(model: str) -> ModelPricing | None:
    """Exact match, then longest-prefix match (dated snapshots like
    ``claude-haiku-4-5-20251001`` / ``gpt-5.5-2026-04-23``)."""
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for known in sorted(MODEL_PRICING, key=len, reverse=True):
        if model.startswith(known):
            return MODEL_PRICING[known]
    return None


def estimate_call_cost(
    model: str, input_tokens: int, output_tokens: int, per_call_input: int | None = None
) -> float | None:
    """Cost in USD for the given token volumes on ``model``; None when
    the model has no published pricing. ``per_call_input`` (typical
    single-request input) decides whether the long-context tier applies.
    """
    p = pricing_for(model)
    if p is None:
        return None
    in_rate, out_rate = p.input_per_m, p.output_per_m
    if (
        p.long_context_threshold
        and per_call_input
        and per_call_input > p.long_context_threshold
    ):
        in_rate = p.long_context_input_per_m or in_rate
        out_rate = p.long_context_output_per_m or out_rate
    return input_tokens / 1_000_000 * in_rate + output_tokens / 1_000_000 * out_rate
