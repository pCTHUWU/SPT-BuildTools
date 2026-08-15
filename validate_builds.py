"""Validate every weapon build in the profile against the real item database.

Checks, per build:
  BAD_SLOT      - the parent template has no slot with that name at all
  NOT_ALLOWED   - the slot exists but its filter does not accept this item
  EXCLUDED      - the slot's ExcludedFilter explicitly rejects this item
  CONFLICT      - two items in the build list each other in ConflictingItems
  ORPHAN        - parentId points at an item that is not in the build
  UNKNOWN_TPL   - template id not present in the database
  MISSING_REQ   - a _required slot on an installed part was left empty

The first five make a build refuse to assemble or behave oddly in the build
screen. MISSING_REQ is reported separately: it is usually intentional for
things like an empty magazine slot, so it is a warning, not a failure.
"""
import io, json, sys
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from options import ITEMS, resolve_profile
from collections import defaultdict

PROFILE = resolve_profile()
ITEMS = ITEMS

items = json.load(io.open(ITEMS, encoding="utf-8"))
prof  = json.load(io.open(PROFILE, encoding="utf-8"))
builds = prof["userbuilds"]["weaponBuilds"]

def name_of(tpl):
    it = items.get(tpl)
    if not it:
        return f"<unknown {tpl}>"
    return it.get("_name") or tpl

# slot lookup: tpl -> {slot_name: (allowed:set, excluded:set, required:bool)}
_slot_cache = {}
def slots_of(tpl):
    if tpl in _slot_cache:
        return _slot_cache[tpl]
    out = {}
    it = items.get(tpl)
    if it:
        for s in (it.get("_props", {}) or {}).get("Slots", []) or []:
            allowed, excluded = set(), set()
            for f in (s.get("_props", {}) or {}).get("filters", []) or []:
                allowed.update(f.get("Filter", []) or [])
                excluded.update(f.get("ExcludedFilter", []) or [])
            out[s.get("_name")] = (allowed, excluded, bool(s.get("_required")))
    _slot_cache[tpl] = out
    return out

def conflicts_of(tpl):
    it = items.get(tpl)
    if not it:
        return set()
    return set((it.get("_props", {}) or {}).get("ConflictingItems", []) or [])

failures = defaultdict(list)   # build name -> [(code, detail)]
warnings = defaultdict(list)
codes = defaultdict(int)

for b in builds:
    bname = b.get("Name", "<unnamed>")
    its = b.get("Items", []) or []
    by_id = {i["_id"]: i for i in its}
    tpls_present = [i["_tpl"] for i in its]

    for it in its:
        tpl, pid, slot = it.get("_tpl"), it.get("parentId"), it.get("slotId")

        if tpl not in items:
            failures[bname].append(("UNKNOWN_TPL", f"{tpl} not in database"))
            codes["UNKNOWN_TPL"] += 1
            continue
        if pid is None:
            continue
        parent = by_id.get(pid)
        if parent is None:
            failures[bname].append(("ORPHAN", f"{name_of(tpl)} parented to missing {pid}"))
            codes["ORPHAN"] += 1
            continue

        ptpl = parent["_tpl"]
        pslots = slots_of(ptpl)
        if slot not in pslots:
            failures[bname].append(
                ("BAD_SLOT", f"{name_of(ptpl)} has no slot '{slot}' (tried to fit {name_of(tpl)})"))
            codes["BAD_SLOT"] += 1
            continue

        allowed, excluded, _ = pslots[slot]
        if tpl in excluded:
            failures[bname].append(
                ("EXCLUDED", f"{name_of(tpl)} is excluded from {name_of(ptpl)}.{slot}"))
            codes["EXCLUDED"] += 1
        elif allowed and tpl not in allowed:
            failures[bname].append(
                ("NOT_ALLOWED", f"{name_of(tpl)} not accepted by {name_of(ptpl)}.{slot}"))
            codes["NOT_ALLOWED"] += 1

    # conflicting items, pairwise but deduped
    seen_pairs = set()
    for it in its:
        c = conflicts_of(it["_tpl"])
        if not c:
            continue
        for other in tpls_present:
            if other != it["_tpl"] and other in c:
                pair = tuple(sorted((it["_tpl"], other)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                failures[bname].append(
                    ("CONFLICT", f"{name_of(pair[0])} conflicts with {name_of(pair[1])}"))
                codes["CONFLICT"] += 1

    # required-but-empty slots on installed parts
    filled = {(i.get("parentId"), i.get("slotId")) for i in its}
    for it in its:
        for sname, (_a, _e, req) in slots_of(it["_tpl"]).items():
            if req and (it["_id"], sname) not in filled:
                warnings[bname].append(("MISSING_REQ", f"{name_of(it['_tpl'])}.{sname} required but empty"))
                codes["MISSING_REQ"] += 1

print(f"builds checked      : {len(builds)}")
print(f"builds with failures: {len(failures)}")
print(f"builds with warnings: {len(warnings)}")
print("\nby code:")
for k in sorted(codes, key=lambda x: -codes[x]):
    print(f"  {k:<12} {codes[k]}")

if failures:
    print("\n" + "=" * 78)
    print("FAILING BUILDS")
    print("=" * 78)
    for bname in sorted(failures):
        print(f"\n{bname}")
        for code, detail in failures[bname][:6]:
            print(f"   [{code}] {detail}")
        if len(failures[bname]) > 6:
            print(f"   ... and {len(failures[bname]) - 6} more")

json.dump({"failures": {k: v for k, v in failures.items()},
           "warnings": {k: v for k, v in warnings.items()}},
          io.open(sys.argv[1], "w", encoding="utf-8") if len(sys.argv) > 1 else io.open(
              "build_report.json", "w", encoding="utf-8"), indent=1)
