"""Step 4. Fresh records + saved ledger/usage.json + phases -> new ledger/usage.json.

Merge rules:
- A saved record whose transcript is gone stays as it was.
- A fresh record replaces the saved one, unless it has fewer calls: part of the
  transcript was cleaned up, and the saved numbers are the better ones.
- feature and phase come from phases.attribute, category from phases.categorize.
- A saved record from before schema 2 has no kind: it reads as "unknown".
- The file is rewritten only when something other than generated_at changed.

Owns the layout of usage.json. A change to it bumps SCHEMA and the record
table in references/details.md.
"""
import json

import measure
import phases
from common import USAGE_FILE, now_iso, parse_ts, write_atomic

SCHEMA = 2


def read_doc(root):
    path = root / USAGE_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def call_count(record):
    return sum(model["calls"] for model in record["models"])


def totals_of(records):
    models = [model for record in records for model in record["models"]]
    totals = {"questions": len(records), "calls": sum(call_count(record) for record in records)}
    for field in measure.TOKEN_FIELDS:
        totals[field] = sum(model[field] for model in models)
    totals["usd"] = round(sum(record["usd"] for record in records), 4)
    totals["active_seconds"] = sum(record["active_seconds"] for record in records)
    return totals


def prices_block(old_doc, records, prices):
    """Rates of every model in the ledger. Models no longer in prices.json keep their saved rates."""
    used = {model["model"] for record in records for model in record["models"]}
    per_mtok = dict(((old_doc.get("prices") or {}).get("per_mtok")) or {})
    per_mtok.update({model: measure.price_snapshot(prices["models"][model]) for model in used if model in prices["models"]})
    return {"source": prices["source"], "as_of": prices["as_of"], "per_mtok": dict(sorted(per_mtok.items()))}


def build_doc(old_doc, fresh, phase_rows, category_rows, prices):
    by_id = {record["id"]: record for record in old_doc.get("questions", [])}
    for record in by_id.values():
        record.setdefault("kind", measure.UNKNOWN_KIND)
        record.setdefault("category", None)
    for record in fresh:
        prior = by_id.get(record["id"])
        if prior and call_count(record) < call_count(prior):
            continue
        record["feature"], record["phase"] = phases.attribute(record, phase_rows, prior)
        record["category"] = phases.categorize(record, category_rows, phase_rows, prior)
        by_id[record["id"]] = record
    records = sorted(by_id.values(), key=lambda record: parse_ts(record["asked_at"]))
    return {
        "schema": SCHEMA,
        "generated_at": old_doc.get("generated_at") or now_iso(),
        "cost_basis": "api_list_price",
        "currency": "USD",
        "prices": prices_block(old_doc, records, prices),
        "totals": totals_of(records),
        "questions": records,
    }


def save_doc(root, old_doc, doc):
    """Write usage.json if it changed. Returns whether it was written."""
    if old_doc and {**old_doc, "generated_at": ""} == {**doc, "generated_at": ""}:
        return False
    doc["generated_at"] = now_iso()
    write_atomic(root / USAGE_FILE, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return True
