"""Score cached extractions against the local answer key (evaluation only).

The answer key is read from data/ground_truth on this machine. The pipeline
itself never reads it.
"""
import argparse
import json
from pathlib import Path

from google.cloud import storage

from pipeline import config
from pipeline.extract import EXTRACT_PREFIX
from pipeline.normalise import canonical

TRUTH_DIR = Path(__file__).resolve().parent.parent / "data" / "ground_truth"


def evaluate(claim, payload):
    truth = json.loads((TRUTH_DIR / f"{claim}.json").read_text())
    fields = payload["fields"]
    wrong, right = [], 0
    for name in truth["scored_fields"]:
        t = truth["fields"][name]
        expected = None if t is None else canonical(name, str(t))
        got = fields[name]["canon"]
        if got == expected:
            right += 1
        else:
            wrong.append(f"{name}: got {fields[name]['value']!r}, expected {t!r}")
    found_conf = {n for n, f in fields.items() if f["status"] == "conflict"}
    no_third_party = fields["third_party_involved"]["canon"] is False
    found_miss = {n for n, f in fields.items()
                  if f["status"] in ("missing", "unparsed")
                  and not (n == "third_party_name" and no_third_party)}
    ungrounded = [n for n, f in fields.items() if f["status"] == "ungrounded"]
    return {
        "tier": truth["tier"], "right": right, "total": len(truth["scored_fields"]),
        "wrong": wrong, "ungrounded": ungrounded,
        "conflict_ok": found_conf == set(truth["expected_flags"]["conflicting"]),
        "missing_ok": found_miss == set(truth["expected_flags"]["missing"]),
        "found_conf": sorted(found_conf), "found_miss": sorted(found_miss),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", nargs="+", required=True)
    args = ap.parse_args()
    bucket = storage.Client(project=config.PROJECT_ID).bucket(config.INBOX_BUCKET)
    right = total = 0
    for claim in args.claim:
        payload = json.loads(bucket.blob(f"{EXTRACT_PREFIX}{claim}.json").download_as_text())
        r = evaluate(claim, payload)
        right += r["right"]
        total += r["total"]
        print(f"{claim} [{r['tier']}] {r['right']}/{r['total']} correct | "
              f"conflict flags {'OK' if r['conflict_ok'] else r['found_conf']} | "
              f"missing flags {'OK' if r['missing_ok'] else r['found_miss']} | "
              f"ungrounded {r['ungrounded'] or 'none'}")
        for w in r["wrong"]:
            print(f"    WRONG {w}")
    print(f"overall: {right}/{total} = {right / total:.1%}")


if __name__ == "__main__":
    main()
