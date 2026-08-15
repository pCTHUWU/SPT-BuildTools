"""Find slots being filled for no gain.

The launcher was one instance of a general habit: the generator fills any slot it legally can,
and a part that fits is not always a part worth fitting. This looks for the rest of that pattern
rather than for launchers specifically.

Three questions per fitted part:

  DEAD WEIGHT   does it cost ergonomics or recoil while doing nothing else?
  EMPTY MOUNT   is it a rail or mount carrying nothing, so it exists only to hold air?
  NO GOOD PICK  was every candidate for that slot net-negative, so filling it was a loss
                whichever one won?

A part earns its place if it carries something, or if it does a job the numbers cannot see -
a sight, a light, a suppressor, a magazine, a stock, a grip.
"""
import io, json, os, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from options import ITEMS, resolve_profile

items = json.load(io.open(ITEMS, encoding="utf-8"))
prof = json.load(io.open(resolve_profile(), encoding="utf-8"))
builds = prof["userbuilds"]["weaponBuilds"]

_c = {}
def cats(t):
    if t not in _c:
        o, cur, n = [], items.get(t), 0
        while cur and n < 14:
            o.append(cur.get("_name") or "")
            cur = items.get(cur.get("_parent")); n += 1
        _c[t] = o
    return _c[t]

def props(t):
    return (items.get(t) or {}).get("_props") or {}

def ergo(t):
    return props(t).get("Ergonomics", 0) or 0

def recoil(t):
    return props(t).get("Recoil", 0) or 0

def nm(t):
    return (items.get(t) or {}).get("_name") or t

# Categories that do a job the ergo/recoil numbers cannot express.
FUNCTIONAL = ("Collimator", "CompactCollimator", "OpticScope", "AssaultScope", "SpecialScope",
              "Flashlight", "TacticalCombo", "Silencer", "Magazine", "Stock", "Foregrip",
              "Bipod", "IronSight", "Barrel", "Receiver", "Handguard", "GasBlock",
              "PistolGrip", "ChargingHandle", "MuzzleCombo", "MuzzleDevice", "Launcher",
              "GrenadeLauncher", "AuxiliaryMod")

def functional(t):
    return any(c in cats(t) for c in FUNCTIONAL)

def is_mount(t):
    c = cats(t)
    return ("Mount" in c or "MountsAndAdapters" in c) and not functional(t)

# ---------------------------------------------------------------- scan
dead = Counter()          # part -> times fitted while costing and giving nothing
dead_cost = {}
empty_mounts = Counter()
slot_examples = defaultdict(str)
no_good_slot = Counter()

for b in builds:
    by_id = {i["_id"]: i for i in b["Items"]}
    kids = defaultdict(list)
    for i in b["Items"]:
        if i.get("parentId"):
            kids[i["parentId"]].append(i)

    for i in b["Items"]:
        t = i["_tpl"]
        if not i.get("parentId"):
            continue
        e, r = ergo(t), recoil(t)
        has_kids = bool(kids.get(i["_id"]))

        # A mount holding nothing AND giving nothing. A rail that adds ergonomics is worth
        # fitting on its own; a ring cap that exists to complete a mount is not "empty".
        if is_mount(t) and not has_kids and e <= 0 and r >= 0:
            empty_mounts[nm(t)] += 1
            dead_cost[nm(t)] = (e, r)
            slot_examples[("mount", nm(t))] = b["Name"]

        # Loses on BOTH axes. Recoil here is a reduction percentage, so a negative value is a
        # gain - a muzzle brake at ergo -1 / recoil -6 is doing exactly its job, and an earlier
        # version of this audit called 137 of those dead weight. Only ergo<=0 AND recoil>=0 is
        # a part that costs and returns nothing.
        if not functional(t) and not has_kids and e <= 0 and r >= 0 and (e < 0 or r > 0):
            dead[nm(t)] += 1
            dead_cost[nm(t)] = (e, r)
            slot_examples[("dead", nm(t))] = b["Name"]

print(f"scanned {len(builds)} builds, {sum(len(b['Items']) for b in builds):,} parts\n")

print("=== EMPTY MOUNTS - rails and mounts carrying nothing ===")
if empty_mounts:
    tot = sum(empty_mounts.values())
    print(f"  {tot} fitted across the profile")
    for n, c in empty_mounts.most_common(12):
        e, r = dead_cost.get(n, (0, 0))
        print(f"   {c:>4}x  {n[:52]:<52} ergo {e:+}  recoil {r:+}")
        print(f"          e.g. {slot_examples[('mount', n)]}")
else:
    print("  none")

print("\n=== DEAD WEIGHT - costs ergonomics or recoil, does nothing, holds nothing ===")
if dead:
    print(f"  {sum(dead.values())} fitted across the profile")
    for n, c in dead.most_common(12):
        e, r = dead_cost[n]
        print(f"   {c:>4}x  {n[:52]:<52} ergo {e:+}  recoil {r:+}")
        print(f"          e.g. {slot_examples[('dead', n)]}")
else:
    print("  none")

# ------------------------------------------------- slots where nothing was worth taking
print("\n=== SLOTS WHERE EVERY CANDIDATE IS A LOSS ===")
print("  (filling these costs something no matter which part wins)")
seen = set()
rows = []
for b in builds:
    for i in b["Items"]:
        parent = next((x for x in b["Items"] if x["_id"] == i.get("parentId")), None)
        if parent is None:
            continue
        slot = i.get("slotId")
        key = (parent["_tpl"], slot)
        if key in seen:
            continue
        seen.add(key)
        for s in props(parent["_tpl"]).get("Slots", []) or []:
            if s.get("_name") != slot:
                continue
            f = (s.get("_props") or {}).get("filters", [{}])[0]
            cands = [c for c in (f.get("Filter") or []) if items.get(c)]
            if not cands:
                continue
            if all(not functional(c) and ergo(c) <= 0 and recoil(c) >= 0 and (ergo(c) < 0 or recoil(c) > 0) for c in cands):
                rows.append((slot, nm(parent["_tpl"]), len(cands)))
if rows:
    agg = Counter(r[0] for r in rows)
    for slot, n in agg.most_common(10):
        ex = next(r for r in rows if r[0] == slot)
        print(f"   {n:>4} host(s)  slot {slot:<22} e.g. on {ex[1][:40]} ({ex[2]} candidates)")
else:
    print("  none")
