"""Build one variant per trader loyalty level, to exercise the trader/flea fallback.

For level N, every slot is filled with the best part any trader sells at loyalty N or below.
Required slots no trader covers at that level fall back to the best part overall, which is
flea-only by definition - that is the case worth testing.

Default: M4A1 only.  --all: every weapon in the game.  --write saves.
Only ever touches builds tagged '(LL)'.
"""
import json, os, random, sys, collections
from options import OPT, DB_DIR, resolve_profile
from buildlib import (MAX_MOUNTS, narrow, score, set_policy, is_auto, set_auto, EARNS_PLACE, LIGHT_CATS, LONG_CAL, LOOKAHEAD, NOT_MOUNTING, OPTIC_CATS, 
    QUIET_WEIGHT, SHORT_CAL, STANDING, WEAPON_BASE, _SLOT_RANK, _cat, _conf, _inflight, _knee, 
    _mag_capacity, _mag_footprint, _reach, build_loudness, build_stats, buyable_now, by_trader, 
    can_carry_optic, capacity, categories, compatible, conflicts, db, dominates, earns_place, 
    is_combo, is_light, is_magazine, is_mounting_part, is_optic, is_stock_slot, is_suppressor, 
    is_weapon, loc, loyalty, mag_slots, name, new_id, objective, optic_class, optic_policy, 
    optic_rank, optic_reach, optic_tiers, pareto_front, prune_empty, shape_ok, short_name, 
    slot_rank, slot_required, suppressor_friendly, usable, weapon_is_auto, weapon_weights, 
    zoom_levels)

ROOT = DB_DIR
PROF = resolve_profile()
M4A1 = "5447a9cd4bdc2dbd208b4567"
TAG  = "(LL)"


SKIP = {"mod_charge_001"}

# See make_builds.py for the full reasoning. Short version: a slot's own filter says nothing about
# ConflictingItems, which is a cross-slot rule (railed dust cover vs standard rear sight, grip with
# integrated stock vs separate stock, handguard longer than its barrel). Picking the best part per
# slot independently broke 248 of 760 builds.

FORCED = []


# How many mounting parts a sight is worth. Two adapters to reach a scope is a mount;
# four is a tower, and the ergonomics score rewards building one because plates read
# positive. Past this the best sight reachable within the cap wins instead.


# See make_builds.py. With conflict checking, sibling slot order decides who wins a contested
# pair, so it has to be chosen. Stock chain first: the Hera Arms CQR family are grips with an
# integrated stock that conflict with every real stock, and filling the grip first left rifles
# with a bare buffer tube and nothing on it.


RECORDING = True     # suppress FORCED logging while refinement is trying things out

def grow(tpl, parent_id, slot_name, depth, chain, placed, w, level, out):
    def add(tpl, parent=None, slot=None, depth=0, chain=()):
        node = {"_id": new_id(), "_tpl": tpl}
        if parent:
            node["parentId"] = parent; node["slotId"] = slot
        out.append(node)
        placed.add(tpl)
        if depth >= 6:
            return
        for s in sorted(db[tpl]["_props"].get("Slots", []),
                        key=lambda x: slot_rank(x.get("_name"))):
            if s["_name"] in SKIP:
                continue
            allowed = s["_props"]["filters"][0]["Filter"]
            # Widen in the original order: tier-legal first, then any usable part, then anything
            # at all - the last two only for required slots, as before.
            # A stock counts as must-fill even though the database marks it optional. At loyalty
            # level 1 no trader sells one for most guns, so the tier pool comes back empty and the
            # slot was simply skipped - leaving 55 builds with no shoulder stock at all. These
            # builds are explicitly the flea-fallback test, so a stock that has to come off the
            # flea is the expected answer, not a reason to go without.
            must = s["_required"] or (OPT["stock"] and is_stock_slot(s))

            tiers = [[c for c in allowed
                      if usable(c) and c not in chain
                      and loyalty.get(c) is not None and loyalty[c] <= level]]
            if must:
                tiers.append([c for c in allowed if usable(c) and c not in chain])
                tiers.append([c for c in allowed
                              if db.get(c) and db[c].get("_props") and c not in chain])

            # Exhaust every widening step looking for a compatible part before settling for a
            # conflicting one. Taking a conflicting tier-legal part when a compatible part exists
            # one step wider would defeat the whole fix.
            pool = next((ok for ok in ([c for c in t if compatible(c, placed)] for t in tiers) if ok), [])
            if not pool:
                if not must:
                    continue
                pool = next((t for t in tiers if t), [])
                if not pool:
                    continue
                if RECORDING:
                    FORCED.append(f"{name(tpl)}.{s['_name']}")
            # Narrowing may empty a slot on purpose, but never a REQUIRED one - the game will not
            # assemble the parent without it. See make_builds.py; MAX_MOUNTS was refusing the
            # Geissele ring cap and leaving an unfillable hole.
            narrowed = narrow(pool, s["_name"], placed, chain + (tpl,))
            pool = narrowed if narrowed or not s["_required"] else pool
            if not pool:
                continue
            best = max(pool, key=lambda c: score(c, s["_name"], w))
            add(best, node["_id"], s["_name"], depth + 1, chain + (tpl,))
    add(tpl, parent_id, slot_name, depth, chain)

def _swap(items, node, alt, w, level):
    drop, changed = {node["_id"]}, True
    while changed:
        changed = False
        for i in items:
            if i.get("parentId") in drop and i["_id"] not in drop:
                drop.add(i["_id"]); changed = True
    keep = [i for i in items if i["_id"] not in drop]
    placed = {i["_tpl"] for i in keep}
    if not compatible(alt, placed):
        return None
    chain, cur = [], next((x for x in keep if x["_id"] == node.get("parentId")), None)
    while cur:
        chain.append(cur["_tpl"])
        cur = next((x for x in keep if x["_id"] == cur.get("parentId")), None)
    sub = []
    grow(alt, node["parentId"], node["slotId"], len(chain), tuple(chain), placed, w, level, sub)
    return keep + sub

def refine(items, w, level, rounds=3, breadth=6):
    """Greedy fills each slot knowing nothing about what follows, so an early pick can be a poor
    fit for the finished gun. Sweep it and keep any single swap that improves the whole weapon.

    Alternatives are restricted to what this loyalty tier can actually buy, so refinement cannot
    quietly smuggle in a part the tier was meant to exclude."""
    if not OPT["refine"]:
        return items
    global RECORDING
    was, RECORDING = RECORDING, False
    best = items
    try:
        for _ in range(rounds):
            improved = False
            for idx in range(1, len(best)):
                node = best[idx]
                parent = next((x for x in best if x["_id"] == node.get("parentId")), None)
                if parent is None:
                    continue
                slot = next((s for s in db[parent["_tpl"]]["_props"].get("Slots", []) or []
                             if s["_name"] == node.get("slotId")), None)
                if not slot:
                    continue
                alts = [c for c in slot["_props"]["filters"][0]["Filter"]
                        if c != node["_tpl"] and usable(c)
                        and loyalty.get(c) is not None and loyalty[c] <= level]
                alts.sort(key=lambda c: score(c, node["slotId"], w), reverse=True)
                for alt in alts[:breadth]:
                    cand = _swap(best, node, alt, w, level)
                    if cand and shape_ok(cand, best, w) and objective(cand, w) > objective(best, w) + 1e-9:
                        best, improved = cand, True
                        break
                if improved:
                    break
            if not improved:
                break
    finally:
        RECORDING = was
    return best

# Categories that do a job the ergonomics/recoil numbers cannot express, so they earn their place
# even at a cost. Bipods are handled separately - see earns_place.


# ---- Pareto selection. See make_builds.py for the reasoning; this is the same machinery with the
# loyalty level threaded through, so both generators pick builds the same way. ----

WEIGHT_SWEEP = [(1.0, 2.0), (1.4, 1.4), (1.8, 0.8)]


def _one(weapon, level, w):
    items, placed = [], set()
    grow(weapon, None, None, 0, (), placed, w, level, items)
    return prune_empty(refine(items, w, level))

def make(weapon, level):
    set_policy(optic_policy(weapon))
    set_auto(weapon_is_auto(weapon))

    if not OPT["pareto"]:
        items = _one(weapon, level, weapon_weights(weapon))
    else:
        wanted_suppressed = OPT["suppressor"]
        variants = []
        for suppressed in ([True, False] if wanted_suppressed else [False]):
            OPT["suppressor"] = suppressed          # single-threaded; restored below
            for w in WEIGHT_SWEEP:
                cand = _one(weapon, level, w)
                ergo, up, _back, _pct, acc = build_stats(cand)
                variants.append(((ergo, acc, -up, -build_loudness(cand)), (cand, w, suppressed)))
        OPT["suppressor"] = wanted_suppressed

        front = pareto_front(variants) or variants

        # See make_builds.py: the frontier decides, not a fixed ergonomics budget. A suppressed
        # build that survives it is not dominated on ergonomics, accuracy and recoil together, so
        # the stated preference for quiet stands.
        pool = front
        if wanted_suppressed:
            quiet = [p for p in front if p[1][2]]
            if quiet:
                pool = quiet

        items = _knee(pool)[1][0]

    stats = collections.Counter()
    for n in items[1:]:
        stats["buy_now" if buyable_now(n["_tpl"]) else "needs_flea"] += 1
    return items, stats

# ---- pick the weapons ----
if "--all" in sys.argv:
    guns, seen = [], {}
    for tpl, it in sorted(db.items(), key=lambda kv: name(kv[0])):
        if it.get("_type") != "Item" or not is_weapon(tpl):
            continue
        if not it["_props"].get("Slots"):
            continue
        s = short_name(tpl)
        seen[s] = seen.get(s, 0) + 1
        guns.append((tpl, s if seen[s] == 1 else f"{s} #{seen[s]}"))
else:
    guns = [(M4A1, short_name(M4A1))]

builds = []
totals = collections.Counter()
for tpl, short in guns:
    for level in (1, 2, 3, 4):
        items, stats = make(tpl, level)
        builds.append({
            "Id": new_id(),
            "Name": f"{short} - loyalty lvl {level} {TAG}",
            "Root": items[0]["_id"],
            "Items": items,
        })
        totals[f"L{level}_buy"]  += stats["buy_now"]
        totals[f"L{level}_flea"] += stats["needs_flea"]

print(f"{len(guns)} weapon(s) x 4 levels = {len(builds)} builds, "
      f"{sum(len(b['Items']) for b in builds):,} parts\n")
if FORCED:
    print(f"  {len(FORCED)} required slot(s) could only be filled with a conflicting part:")
    for f in sorted(set(FORCED)):
        print(f"    {f}")
    print()
print("  across all builds, parts that would come from each source:")
for level in (1, 2, 3, 4):
    b, f = totals[f"L{level}_buy"], totals[f"L{level}_flea"]
    tot = b + f or 1
    print(f"    loyalty lvl {level}: {b:>5} from your traders, {f:>5} off the flea  ({f*100//tot}% flea)")

if "--write" in sys.argv:
    prof = json.load(open(PROF, encoding="utf-8"))
    kept = [x for x in prof["userbuilds"]["weaponBuilds"] if TAG not in (x.get("Name") or "")]
    prof["userbuilds"]["weaponBuilds"] = kept + builds
    with open(PROF, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nWritten. kept {len(kept)} existing builds, added {len(builds)}.")
else:
    print("\n(preview only - pass --write to save)")
