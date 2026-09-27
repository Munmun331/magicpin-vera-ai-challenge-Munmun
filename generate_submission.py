#!/usr/bin/env python3
"""
Generates the 30-line submission.jsonl by running the canonical test pairs
through the general compose() engine.
"""

import json
from pathlib import Path

from app.composer import compose
from app.validator import OutputValidator


def generate_submission(
    expanded_dir: Path = Path("expanded"),
    output_file: Path = Path("submission.jsonl"),
):
    test_pairs_path = expanded_dir / "test_pairs.json"
    if not test_pairs_path.exists():
        raise FileNotFoundError(f"Missing {test_pairs_path}. Run generate_dataset.py first.")

    with open(test_pairs_path, "r", encoding="utf-8") as f:
        test_pairs = json.load(f)["pairs"]

    # Preload categories, merchants, customers, triggers
    categories = {}
    for f in (expanded_dir / "categories").glob("*.json"):
        cat = json.load(open(f, encoding="utf-8"))
        categories[cat["slug"]] = cat

    merchants = {}
    for f in (expanded_dir / "merchants").glob("*.json"):
        m = json.load(open(f, encoding="utf-8"))
        merchants[m["merchant_id"]] = m

    customers = {}
    for f in (expanded_dir / "customers").glob("*.json"):
        c = json.load(open(f, encoding="utf-8"))
        customers[c["customer_id"]] = c

    triggers = {}
    for f in (expanded_dir / "triggers").glob("*.json"):
        t = json.load(open(f, encoding="utf-8"))
        triggers[t["id"]] = t

    lines = []
    print(f"Generating submission for {len(test_pairs)} test pairs...")

    for pair in test_pairs:
        test_id = pair["test_id"]
        tid = pair["trigger_id"]
        mid = pair["merchant_id"]
        cid = pair.get("customer_id")

        trigger = triggers.get(tid)
        merchant = merchants.get(mid)
        customer = customers.get(cid) if cid else None

        if not trigger or not merchant:
            print(f"[WARN] Missing trigger or merchant for {test_id}: {tid}, {mid}")
            continue

        cat_slug = merchant.get("category_slug")
        category = categories.get(cat_slug)
        if not category:
            print(f"[WARN] Missing category {cat_slug} for {test_id}")
            continue

        action = compose(category, merchant, trigger, customer)

        # Validate action
        is_valid, errors = OutputValidator.validate_action(action, category)
        if not is_valid:
            print(f"[WARN] Validation issues on {test_id}: {errors}")

        submission_entry = {
            "test_id": test_id,
            "body": action.get("body", ""),
            "cta": action.get("cta", "none"),
            "send_as": action.get("send_as", "vera"),
            "suppression_key": action.get("suppression_key", ""),
            "rationale": action.get("rationale", ""),
        }
        lines.append(submission_entry)

    with open(output_file, "w", encoding="utf-8") as f:
        for entry in lines:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Successfully generated {len(lines)} lines in {output_file}")


if __name__ == "__main__":
    generate_submission()
