"""Task 0 — measure the real Comick gap. Builds nothing.

A "gap" series is one Colosseum cannot currently show a volume shelf for, i.e. one Comick did
not qualify. Two populations, both enumerated here:

  1. a seed with a db/*.json record whose `qualified` is false (Comick tried, the gate refused);
  2. a seed with NO db/*.json record at all (Comick has not been run / resolved it yet).

Pure and offline: reads only seeds.json and db/*.json. Writes reports/gap_list.json and prints
a count plus a breakdown by gateReason. The count sizes every downstream task in the plan.

The Berserk case is recorded here as a gap row but is EXPLICITLY OUT OF SCOPE for the fallback
sources: its refusal is a fractional-chapter (`0.01`) origin problem, a separate normalization
follow-up. Neither Wikipedia nor Fandom fixes a numbering-offset bug, so it is flagged
`inScopeForFallback: false` and must stay refused.
"""
import collections
import json
import pathlib

HERE = pathlib.Path(__file__).parent
SEEDS = HERE / "seeds.json"
DB = HERE.parent / "db"
REPORTS = HERE.parent / "reports"

# The single fractional-origin refusal. The plan (Acceptance #7, Traps) names this deliberately
# out of scope: it is a numbering-normalization problem, not a missing-data problem.
FRACTIONAL_ORIGIN_REASON = "numbering quirk (fractional chapter origin)"


def _load_seeds():
    return json.loads(SEEDS.read_text(encoding="utf-8"))


def _load_records_by_title():
    out = {}
    for p in DB.glob("*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        out[rec["seriesTitle"]] = (p.stem, rec)  # p.stem == weebcentral ulid
    return out


def measure():
    seeds = _load_seeds()
    by_title = _load_records_by_title()

    rows = []
    for title in seeds:
        hit = by_title.get(title)
        if hit is None:
            rows.append({
                "weebCentralId": None,
                "seriesTitle": title,
                "reason": "no db record (seed not yet built)",
                "hasRecord": False,
                "qualified": False,
                "inScopeForFallback": True,
            })
            continue
        ulid, rec = hit
        if rec["qualified"]:
            continue  # Comick already provides the shelf -> never a fallback target
        reason = rec.get("gateReason") or "qualified false (no gateReason)"
        rows.append({
            "weebCentralId": ulid,
            "seriesTitle": title,
            "reason": reason,
            "hasRecord": True,
            "qualified": False,
            # The fractional-chapter-origin refusal is a numbering bug, not missing volume data.
            # Fallback sources cannot fix it; it stays refused.
            "inScopeForFallback": not (reason == FRACTIONAL_ORIGIN_REASON),
        })
    return rows


def main():
    rows = measure()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "gap_list.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    by_reason = collections.Counter(r["reason"] for r in rows)
    in_scope = [r for r in rows if r["inScopeForFallback"]]

    print("=" * 70)
    print("TASK 0 — Comick gap measurement")
    print("=" * 70)
    print(f"Seeds (full population):     {len(_load_seeds())}")
    print(f"Gap series (unqualified + missing): {len(rows)}")
    print(f"  of which IN SCOPE for fallback sources: {len(in_scope)}")
    print(f"  of which OUT OF SCOPE (numbering quirk): {len(rows) - len(in_scope)}")
    print()
    print("Breakdown by gateReason:")
    for reason, n in sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:>3}  {reason}")
    print()
    print("Gap rows:")
    for r in rows:
        flag = "" if r["inScopeForFallback"] else "  [OUT OF SCOPE]"
        print(f"  - {r['seriesTitle']:24} {r['reason']}{flag}")
    print()
    print(f"Wrote {REPORTS / 'gap_list.json'}")


if __name__ == "__main__":
    main()
