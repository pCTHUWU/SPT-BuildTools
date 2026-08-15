"""Magazine footprint across the profile's builds: how many eat a third rig slot, and where the
rule had to give way because the gun has nothing smaller."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from options import ITEMS, resolve_profile

import io, json
from collections import Counter

items = json.load(io.open(ITEMS, encoding="utf-8"))
prof = json.load(io.open(resolve_profile(), encoding="utf-8"))

_c = {}
def cats(t):
    if t not in _c:
        o, cur, n = [], items.get(t), 0
        while cur and n < 14:
            o.append(cur.get("_name") or ""); cur = items.get(cur.get("_parent")); n += 1
        _c[t] = o
    return _c[t]

def slots(t):
    p = items.get(t, {}).get("_props") or {}
    return (p.get("Width") or 0) * (p.get("Height") or 0)

def cap(t):
    c = (items.get(t, {}).get("_props") or {}).get("Cartridges") or []
    return c[0].get("_max_count", 0) if c else 0

def is_mag(t):
    return "Magazine" in cats(t)

# Could this gun have taken something smaller, or was it forced?
def smaller_available(build, mag_id):
    node = next((i for i in build["Items"] if i["_id"] == mag_id), None)
    parent = next((i for i in build["Items"] if i["_id"] == node.get("parentId")), None)
    if not parent:
        return False
    for s in (items.get(parent["_tpl"], {}).get("_props") or {}).get("Slots", []) or []:
        if (s.get("_name") or "") != node.get("slotId"):
            continue
        f = (s.get("_props") or {}).get("filters", [{}])[0]
        return any(0 < slots(c) <= 2 for c in (f.get("Filter") or []))
    return False

foot = Counter()
forced, avoidable = [], []
for b in prof["userbuilds"]["weaponBuilds"]:
    for i in b["Items"]:
        if not is_mag(i["_tpl"]):
            continue
        n = slots(i["_tpl"])
        foot[n] += 1
        if n >= 3:
            (avoidable if smaller_available(b, i["_id"]) else forced).append(
                (b["Name"], items[i["_tpl"]].get("_name"), n, cap(i["_tpl"])))

total = sum(foot.values())
print(f"magazines fitted across {len(prof['userbuilds']['weaponBuilds'])} builds: {total}")
for n in sorted(foot):
    print(f"   {n} slot(s): {foot[n]:>4}")
big = sum(v for k, v in foot.items() if k >= 3)
print(f"\n3+ slots: {big} ({big * 100 // max(total, 1)}%)")
print(f"   forced - gun has nothing smaller : {len(forced)}")
print(f"   avoidable                        : {len(avoidable)}")
for name, mag, n, c in avoidable[:6]:
    print(f"      {name:<34} {mag[:38]:<38} {n} slots, {c} rds")
