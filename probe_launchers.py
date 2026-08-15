"""Where are grenade launchers coming from, and what do they displace?"""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from options import ITEMS, resolve_profile
from collections import Counter

items = json.load(io.open(ITEMS, encoding="utf-8"))
prof = json.load(io.open(resolve_profile(), encoding="utf-8"))

_c = {}
def cats(t):
    if t not in _c:
        o, cur, n = [], items.get(t), 0
        while cur and n < 14:
            o.append(cur.get("_name") or "")
            cur = items.get(cur.get("_parent")); n += 1
        _c[t] = o
    return _c[t]

# find every category name that smells like a launcher
print("=== categories containing 'launcher' or 'grenade' ===")
seen = Counter()
for t, it in items.items():
    if it.get("_type") != "Item":
        continue
    for c in cats(t):
        if "launch" in c.lower() or "grenade" in c.lower():
            seen[c] += 1
for c, n in seen.most_common():
    print(f"   {c:<28} {n}")

LAUNCHER = [c for c in seen if "launch" in c.lower()]
def is_launcher(t):
    return any(c in cats(t) for c in LAUNCHER)

print("\n=== launchers fitted in the current builds ===")
slots = Counter()
names = Counter()
builds = set()
for b in prof["userbuilds"]["weaponBuilds"]:
    for i in b["Items"]:
        if is_launcher(i["_tpl"]):
            slots[i.get("slotId")] += 1
            names[items[i["_tpl"]].get("_name") or i["_tpl"]] += 1
            builds.add(b["Name"])
print(f"   builds carrying one: {len(builds)} of {len(prof['userbuilds']['weaponBuilds'])}")
for s, n in slots.most_common():
    print(f"   slot {str(s):<22} {n}   (None = the launcher is the weapon itself)")
for nm, n in names.most_common(8):
    print(f"      {n:>4}x {nm}")
for b in sorted(builds)[:5]:
    print(f"      e.g. {b}")

print("\n=== what else does mod_launcher accept? ===")
opts = Counter()
for t, it in items.items():
    for s in (it.get("_props") or {}).get("Slots", []) or []:
        if s.get("_name") != "mod_launcher":
            continue
        f = (s.get("_props") or {}).get("filters", [{}])[0]
        for c in (f.get("Filter") or []):
            kind = "LAUNCHER" if is_launcher(c) else next(
                (k for k in ("Foregrip", "Flashlight", "TacticalCombo", "Bipod", "Mount")
                 if k in cats(c)), "other")
            opts[kind] += 1
print("   " + (", ".join(f"{k}={v}" for k, v in opts.most_common()) or "nothing"))

print("\n=== does the launcher cost the build its grip or light? ===")
def has(b, pred):
    return any(pred(i["_tpl"]) for i in b["Items"])
def is_grip(t):   return "Foregrip" in cats(t)
def is_light(t):  return any(c in cats(t) for c in ("Flashlight", "TacticalCombo"))

withl = [b for b in prof["userbuilds"]["weaponBuilds"]
         if any(is_launcher(i["_tpl"]) and i.get("slotId") for i in b["Items"])]
print(f"   builds with a fitted launcher: {len(withl)}")
print(f"      of those, no foregrip : {sum(1 for b in withl if not has(b, is_grip))}")
print(f"      of those, no light    : {sum(1 for b in withl if not has(b, is_light))}")
conf = 0
for b in withl:
    lt = [i["_tpl"] for i in b["Items"] if is_launcher(i["_tpl"]) and i.get("slotId")]
    for l in lt:
        cl = set((items.get(l, {}).get("_props") or {}).get("ConflictingItems") or [])
        if cl:
            conf += 1
            print(f"      {items[l].get('_name')} conflicts with {len(cl)} other parts")
            break
    if conf >= 2:
        break
