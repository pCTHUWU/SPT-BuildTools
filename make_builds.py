"""Generate meta weapon builds for the SPT profile.

Each slot's part is chosen by maximising (Ergonomics - Recoil) among the parts that slot's own
filter allows, so every build is valid by construction rather than by guesswork. Magazines are
scored on capacity instead, since ergonomics alone picks a 10-round PMAG.

Preview by default; pass --write to save into the profile.
"""
import json, random, sys
from options import OPT, ITEMS, LOCALE, resolve_profile
from buildlib import (MAX_MOUNTS, narrow, score, set_policy, is_auto, set_auto, EARNS_PLACE, LIGHT_CATS, LONG_CAL, LOOKAHEAD, NOT_MOUNTING, OPTIC_CATS, 
    QUIET_WEIGHT, SHORT_CAL, WEAPON_BASE, _SLOT_RANK, _cat, _conf, _inflight, _knee, 
    _mag_capacity, _mag_footprint, _reach, build_loudness, build_stats, can_carry_optic, 
    capacity, categories, compatible, conflicts, db, dominates, earns_place, is_combo, is_light, 
    is_magazine, is_mounting_part, is_optic, is_stock_slot, is_suppressor, is_weapon, loc, 
    mag_slots, name, new_id, objective, optic_class, optic_policy, optic_rank, optic_reach, 
    optic_tiers, pareto_front, prune_empty, shape_ok, short_name, slot_rank, slot_required, 
    suppressor_friendly, usable, weapon_is_auto, weapon_weights, zoom_levels)

DB   = ITEMS
LOC  = LOCALE
PROF = resolve_profile()

TAG = "(meta)"                              # marks builds this script owns


# Pick weapons by name so a wrong hardcoded id can't slip through.
WANTED = [
    ("Colt M4A1 5.56x45 assault rifle",                        "M4A1"),
    ("HK 416A5 5.56x45 assault rifle",                         "HK 416A5"),
    ("Kalashnikov AK-74N 5.45x39 assault rifle",               "AK-74N"),
    ("Kalashnikov AKM 7.62x39 assault rifle",                  "AKM"),
    ("SIG MCX-SPEAR 6.8x51 assault rifle",                     "MCX-SPEAR"),
    ("HK G36 5.56x45 assault rifle",                           "G36"),
    ("SIG MPX 9x19 submachine gun",                            "MPX"),
    ("HK MP7A2 4.6x30 submachine gun",                         "MP7A2"),
    ("TDI KRISS Vector Gen.2 9x19 submachine gun",             "Vector 9x19"),
    ("Knight's Armament Company SR-25 7.62x51 marksman rifle", "SR-25"),
    ("Remington R11 RSASS 7.62x51 marksman rifle",             "RSASS"),
    ("Accuracy International AXMC .338 LM bolt-action sniper rifle", "AXMC"),
    ("Remington Model 700 7.62x51 bolt-action sniper rifle",   "M700"),
    ("Mossberg 590A1 12ga pump-action shotgun",                "590A1"),
    ("Degtyarev RPD 7.62x39 machine gun",                      "RPD"),
]


by_name = {}
for tpl, it in db.items():
    if it.get("_type") == "Item" and is_weapon(tpl):
        by_name.setdefault(name(tpl), tpl)

# --all: every weapon in the game, not just the curated list.
if "--all" in sys.argv:
    seen = {}
    WANTED = []
    for full, tpl in sorted(by_name.items()):
        if not db[tpl]["_props"].get("Slots"):
            continue                      # nothing to build - a bare frame
        s = short_name(tpl)
        seen[s] = seen.get(s, 0) + 1
        WANTED.append((full, s if seen[s] == 1 else f"{s} #{seen[s]}"))


SKIP = {"mod_charge_001"}                    # redundant duplicate slots

# A slot's own filter is not the whole compatibility story. ConflictingItems is a *cross-slot*
# rule - a railed dust cover rejecting the standard rear sight, a grip with a built-in stock
# rejecting a separate stock, a handguard longer than the barrel under it. Choosing the best part
# per slot independently, as this script first did, produced 442 such violations across 248 of
# 760 builds: every part legal for its own slot, a third of the builds refusing to assemble.

FORCED = []          # required slots that could only be filled with a conflicting part


# Short range: pistol-calibre and shot. No magnification wanted - a zoom optic on an automatic
# SMG is in the way.


# How many mounting parts a sight is worth. Two adapters to reach a scope is a mount;
# four is a tower, and the ergonomics score rewards building one because plates read
# positive. Past this the best sight reachable within the cap wins instead.


# Sibling slots are filled depth-first in the order the database lists them, and with conflict
# checking that order decides who wins a contested pair. It has to be chosen, not inherited.
#
# The shoulder stock goes first. Several "pistol grips" - the Hera Arms CQR family - are really
# grips with an integrated stock, and they conflict with every real stock. Filling the grip first
# left the rifle with a bare buffer tube and no stock at all: legal, and useless. Filling the stock
# chain first puts a real stock on and pushes the grip to an ordinary compatible one, which is what
# a recoil-focused build wants anyway.


def pick(allowed, chain, placed, required):
    base = [c for c in allowed if usable(c) and c not in chain]
    if not base and required:
        # A required slot must be filled for the build to be valid, even if the only candidates
        # cannot be bought off the flea (the AK-50's barrel, for one).
        base = [c for c in allowed if db.get(c) and db[c].get("_props") and c not in chain]
    ok = [c for c in base if compatible(c, placed)]
    if ok:
        return ok, False
    if base and required:
        return base, True      # boxed in by an earlier pick; an empty required slot is worse
    return [], False

RECORDING = True     # suppress FORCED logging while refinement is trying things out

def grow(tpl, parent_id, slot_name, depth, chain, placed, w, out):
    """Fill tpl's slots depth-first, appending nodes to `out`."""
    node = {"_id": new_id(), "_tpl": tpl}
    if parent_id:
        node["parentId"] = parent_id
        node["slotId"] = slot_name
    out.append(node)
    placed.add(tpl)
    if depth >= 6:
        return
    for s in sorted(db[tpl]["_props"].get("Slots", []),
                    key=lambda x: slot_rank(x.get("_name"))):
        if s["_name"] in SKIP:
            continue
        allowed = s["_props"]["filters"][0]["Filter"]
        # A stock is must-fill even where the database marks it optional - a rifle without one
        # is not a build worth saving.
        cands, forced = pick(allowed, chain, placed, s["_required"] or (OPT["stock"] and is_stock_slot(s)))
        if not cands:
            continue
        if forced and RECORDING:
            FORCED.append(f"{name(tpl)}.{s['_name']}")
        # Narrowing may empty a slot on purpose - a second optic mount, a launcher, a plate past
        # the mount cap. It must never do that to a REQUIRED slot, because the game will not
        # assemble the parent without it. MAX_MOUNTS was refusing the Geissele mount's ring cap,
        # which is required, and left 25 builds with an unfillable hole that surfaced only as a
        # validate warning.
        narrowed = narrow(cands, s["_name"], placed, chain + (tpl,))
        cands = narrowed if narrowed or not s["_required"] else cands
        if not cands:
            continue
        best = max(cands, key=lambda c: score(c, s["_name"], w))
        grow(best, node["_id"], s["_name"], depth + 1, chain + (tpl,), placed, w, out)

def _swap(items, node, alt, w):
    """Replace one part and everything hanging off it. Returns the new item list, or None if the
    replacement is not compatible with what is already on the gun."""
    drop, changed = {node["_id"]}, True
    while changed:                       # node's whole subtree goes with it
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
    grow(alt, node["parentId"], node["slotId"], len(chain), tuple(chain), placed, w, sub)
    return keep + sub

def refine(items, w, rounds=3, breadth=6):
    """Greedy fills each slot knowing nothing about what comes after it, so a part chosen early
    can be a poor fit for the finished gun. Sweep the built weapon and try swapping each part for
    its alternatives, keeping any change that improves the weapon as a whole."""
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
                        if c != node["_tpl"] and usable(c)]
                alts.sort(key=lambda c: score(c, node["slotId"], w), reverse=True)
                for alt in alts[:breadth]:
                    cand = _swap(best, node, alt, w)
                    if cand and shape_ok(cand, best, w) and objective(cand, w) > objective(best, w) + 1e-9:
                        best, improved = cand, True
                        break
                if improved:
                    break                # list indices shifted; restart the sweep
            if not improved:
                break
    finally:
        RECORDING = was
    return best

# Categories that do a job the ergonomics/recoil numbers cannot express, so they earn their place
# even at a cost. Bipods are handled separately - see earns_place.


# One fixed weighting bakes the same ergonomics-versus-recoil trade into every gun, and it is the
# wrong trade at both ends. Build several and keep the ones nothing else beats outright.
WEIGHT_SWEEP = [(1.0, 2.0), (1.4, 1.4), (1.8, 0.8)]


def make(weapon_tpl):
    set_policy(optic_policy(weapon_tpl))
    set_auto(weapon_is_auto(weapon_tpl))

    if not OPT["pareto"]:
        w = weapon_weights(weapon_tpl)
        items, placed = [], set()
        grow(weapon_tpl, None, None, 0, (), placed, w, items)
        return prune_empty(refine(items, w)), w

    wanted_suppressed = OPT["suppressor"]
    variants = []
    for suppressed in ([True, False] if wanted_suppressed else [False]):
        OPT["suppressor"] = suppressed          # single-threaded; restored below
        for w in WEIGHT_SWEEP:
            items, placed = [], set()
            grow(weapon_tpl, None, None, 0, (), placed, w, items)
            items = prune_empty(refine(items, w))
            ergo, up, _back, _pct, acc = build_stats(items)
            variants.append(((ergo, acc, -up, -build_loudness(items)), (items, w, suppressed)))
    OPT["suppressor"] = wanted_suppressed

    front = pareto_front(variants) or variants

    # Suppressed by preference, decided by the frontier rather than a fixed ergonomics budget.
    #
    # The old rule compared best-quiet against best-loud on *ergonomics alone* and went loud if the
    # gap beat SUPPRESSOR_ERGO_BUDGET = 12. That judged a three-way trade on one axis: a suppressor
    # also cuts recoil (every one in this database does, -7 to -15) and cuts noise, which is the
    # entire reason to fit one. At a budget of 12 the M4A1's -28 can and the SVD's -22 both lost,
    # i.e. "prefer suppressed" almost never held.
    #
    # The frontier already answers this properly: it has removed everything beaten outright on
    # ergonomics, accuracy *and* recoil together. So a suppressed build that survives is not
    # dominated, and the stated preference stands. If every quiet candidate is dominated, none
    # survive and the loud build wins on merit rather than on a threshold.
    pool = front
    if wanted_suppressed:
        quiet = [p for p in front if p[1][2]]
        if quiet:
            pool = quiet

    chosen = _knee(pool)
    return chosen[1][0], chosen[1][1]

builds = []
missing = []
STATS = []
for want, short in WANTED:
    tpl = by_name.get(want)
    if not tpl:
        missing.append(want); continue
    items, w = make(tpl)
    builds.append({
        "Id": new_id(),
        "Name": f"{short} {TAG}",
        "Root": items[0]["_id"],
        "Items": items,
    })
    ergo, up, back, pct, acc = build_stats(items)
    STATS.append((short, ergo, up, pct))
    kind = "auto" if weapon_is_auto(tpl) else "semi"
    print(f"  {short:<12} {len(items):>3} parts  {kind}  ergo {ergo:>4.0f}  "
          f"recoil {up:>5.0f}/{back:>5.0f} ({pct:+.0f}%)  acc {acc:+4.0f}   {want}")

if missing:
    print("\nNOT FOUND (name mismatch):")
    for m in missing:
        print("  " + m)

print(f"\n{len(builds)} build(s), {sum(len(b['Items']) for b in builds)} parts total")
if FORCED:
    print(f"\n{len(FORCED)} required slot(s) could only be filled with a conflicting part:")
    for f in sorted(set(FORCED)):
        print(f"    {f}")

if "--write" in sys.argv:
    prof = json.load(open(PROF, encoding="utf-8"))
    kept = [b for b in prof["userbuilds"]["weaponBuilds"] if TAG not in (b.get("Name") or "")]
    prof["userbuilds"]["weaponBuilds"] = kept + builds
    with open(PROF, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Written. kept {len(kept)} existing, added {len(builds)}.")
else:
    print("(preview only - pass --write to save)")
