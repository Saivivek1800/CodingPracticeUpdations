"""Build input_evaluation_metrics.json from input.json (per-question test case evaluation metrics)."""

import json
import sys


def _extract_from_item(item: dict, out: dict) -> None:
    if not isinstance(item, dict):
        return
    q = item.get("question") if isinstance(item.get("question"), dict) else {}
    qid = q.get("question_id") or item.get("question_id")
    raw = item.get("test_case_evaluation_metrics")
    if not qid or not isinstance(raw, list) or not raw:
        return
    cleaned = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        lang = row.get("language")
        if lang is None:
            continue
        tl = row.get("time_limit_to_execute_in_seconds")
        if tl is None:
            tl = row.get("execution_time_in_seconds")
        if tl is None:
            continue
        cleaned.append(
            {
                "language": str(lang).strip(),
                "time_limit_to_execute_in_seconds": float(tl),
            }
        )
    if cleaned:
        out[str(qid)] = cleaned


def main() -> None:
    try:
        with open("input.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        by_q: dict = {}
        if isinstance(data, list):
            for item in data:
                _extract_from_item(item, by_q)
        elif isinstance(data, dict):
            _extract_from_item(data, by_q)

        payload = {"evaluation_metrics_by_question": by_q}
        with open("input_evaluation_metrics.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
        print("Successfully formatted input.json to input_evaluation_metrics.json")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
