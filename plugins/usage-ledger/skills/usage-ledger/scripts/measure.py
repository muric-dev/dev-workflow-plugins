"""Step 3. Question -> record: tokens, list-price USD, and active time.

Input: a question from transcripts.py and the price table in assets/prices.json.
Output: one record per question, with one entry per (model, effort):
    {"id", "session", "asked_at", "feature", "phase", "kind", "category",
     "models": [{"model", "effort", "calls", <TOKEN_FIELDS>, "usd"}],
     "usd", "active_seconds"}

A new model or price goes in assets/prices.json, not here. Change this module
only when a pricing rule changes (tiers, multipliers) or a record gains a field.
"""
import json
import re
from pathlib import Path

from common import UNASSIGNED

PRICES_FILE = Path(__file__).resolve().parent.parent / "assets" / "prices.json"
IDLE_CAP_SECONDS = 300

# A question whose turn called one of these changed files: it is work. Bash is left
# out because a sed and a grep look the same from the tool name.
EDIT_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})
WORK, QUESTION, UNKNOWN_KIND = "work", "question", "unknown"

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "thinking_tokens",  # A subset of output_tokens, never priced on its own.
    "cache_read_tokens",
    "cache_write_5m_tokens",
    "cache_write_1h_tokens",
)
# Price per million tokens in prices.json -> the token count it applies to.
PRICED_TOKENS = {
    "input": "input_tokens",
    "cache_write_5m": "cache_write_5m_tokens",
    "cache_write_1h": "cache_write_1h_tokens",
    "cache_read": "cache_read_tokens",
    "output": "output_tokens",
}


def load_prices():
    return json.loads(PRICES_FILE.read_text(encoding="utf-8"))


def normalize_model(model):
    """claude-opus-5-5[1m], us.anthropic.claude-opus-5-5-v1:0 -> claude-opus-5-5."""
    model = re.sub(r"\[.*\]$", "", model or "unknown")
    model = re.sub(r"^.*anthropic\.", "", model)
    model = re.sub(r"-v\d+(:\d+)?$", "", model)
    return re.sub(r"-\d{8}$", "", model)


def call_tokens(usage):
    cache = usage.get("cache_creation") or {}
    write_5m = cache.get("ephemeral_5m_input_tokens")
    write_1h = cache.get("ephemeral_1h_input_tokens")
    if write_5m is None and write_1h is None:  # Older transcripts have no 5m/1h split.
        write_5m, write_1h = usage.get("cache_creation_input_tokens") or 0, 0
    details = usage.get("output_tokens_details") or {}
    return {
        "input_tokens": usage.get("input_tokens") or 0,
        "output_tokens": usage.get("output_tokens") or 0,
        "thinking_tokens": details.get("thinking_tokens") or 0,
        "cache_read_tokens": usage.get("cache_read_input_tokens") or 0,
        "cache_write_5m_tokens": write_5m or 0,
        "cache_write_1h_tokens": write_1h or 0,
    }


def call_cost(model, usage, tokens, prices):
    """USD for one call, or None when the model has no price."""
    entry = prices["models"].get(model)
    if entry is None:
        return None
    prompt = sum(tokens[field] for rate, field in PRICED_TOKENS.items() if rate != "output")
    over = entry.get("over")
    rates = over if over and prompt > over["prompt_tokens"] else entry
    multiplier = 1.0
    if usage.get("speed") == "fast":
        multiplier *= entry.get("fast_multiplier", 1.0)
    if usage.get("inference_geo") == "us" and entry.get("geo_premium", True):
        multiplier *= prices["us_multiplier"]
    raw = sum(tokens[field] * rates[rate] for rate, field in PRICED_TOKENS.items())
    return multiplier * raw / 1_000_000


def active_seconds(question):
    """Claude Code's turn_duration when logged, else event gaps capped at IDLE_CAP_SECONDS."""
    if question["turn_ms"]:
        return round(question["turn_ms"] / 1000)
    stamps = sorted(question["stamps"])
    gaps = ((later - earlier).total_seconds() for earlier, later in zip(stamps, stamps[1:]))
    return round(sum(min(gap, IDLE_CAP_SECONDS) for gap in gaps))


def kind_of(question):
    return WORK if question["tools"] & EDIT_TOOLS else QUESTION


def build_record(question, prices):
    groups = {}
    for line in question["calls"].values():
        usage = line["message"]["usage"]
        model = normalize_model(line["message"].get("model"))
        effort = line.get("effort") or "unknown"
        group = groups.setdefault(
            (model, effort),
            {"model": model, "effort": effort, "calls": 0, **dict.fromkeys(TOKEN_FIELDS, 0), "usd": 0.0},
        )
        tokens = call_tokens(usage)
        group["calls"] += 1
        for field in TOKEN_FIELDS:
            group[field] += tokens[field]
        group["usd"] += call_cost(model, usage, tokens, prices) or 0.0
    total = sum(group["usd"] for group in groups.values())
    for group in groups.values():
        group["usd"] = round(group["usd"], 4)
    return {
        "id": question["id"],
        "session": question["session"],
        "asked_at": question["asked_at"],
        "feature": UNASSIGNED,  # Set by document.build_doc from phases.csv.
        "phase": UNASSIGNED,
        "kind": kind_of(question),
        "category": None,  # Set by document.build_doc from categories.csv.
        "models": list(groups.values()),
        "usd": round(total, 4),
        "active_seconds": active_seconds(question),
    }


def unpriced_models(records, prices):
    """Models that were used but have no entry in prices.json, so they counted as 0 USD."""
    used = {model["model"] for record in records for model in record["models"]}
    return sorted(used - set(prices["models"]))


def price_snapshot(entry):
    """The rates saved in usage.json, so readers know what each model was priced at."""
    rates = {rate: entry[rate] for rate in PRICED_TOKENS}
    if entry.get("over"):
        rates["over"] = entry["over"]
    return rates
