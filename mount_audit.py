"""What does each build pay to mount its sight, and is the sight worth it?

Mount parts are chosen slot by slot on their own ergonomics, with no view of what they end up
carrying. So a build can spend several points of ergonomics on a rail, a riser and a ring to hold
a red dot that another mount would have carried for nothing - or worse, that could have gone
straight onto the receiver.

For each build: find the optic, walk back to the first structural part (weapon, receiver or
handguard), and total what the hardware in between costs. Then ask whether a cheaper path to the
same optic existed.
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

def nm(t):
    return (items.get(t) or {}).get("_name") or t

OPTIC = ("Collimator", "CompactCollimator", "OpticScope", "AssaultScope", "SpecialScope")
STRUCTURAL = ("Weapon", "Receiver", "Handguard", "Barrel", "Stock", "PistolGrip")

def is_optic(t):
    return any(c in cats(t) for c in OPTIC)

def is_structural(t):
    return any(c in cats(t) for c in STRUCTURAL)

# Anything whose only job is to hold something else up. A suppressor that happens to carry a rail
# is not mounting hardware - it is a suppressor.
NOT_MOUNTING = ("Silencer", "Barrel", "Receiver", "Handguard", "GasBlock", "Stock",
                "PistolGrip", "Magazine", "Foregrip", "Bipod", "Flashlight", "TacticalCombo")

def is_mounting(t):
    c = cats(t)
    if any(x in c for x in NOT_MOUNTING) or is_optic(t):
        return False
    return "Mount" in c or "MountsAndAdapters" in c

# --------------------------------------------------------------- per build
rows = []
for b in builds:
    by_id = {i["_id"]: i for i in b["Items"]}
    for i in b["Items"]:
        if not is_optic(i["_tpl"]):
            continue
        # Only hardware that exists to carry the sight counts. Walking until the first structural
        # part swept in the suppressor on pistols - where the optic sits on the can - and charged
        # its -13 ergonomics to the mount, which is not what the suppressor is there for.
        chain = []
        cur = by_id.get(i.get("parentId"))
        while cur is not None and is_mounting(cur["_tpl"]):
            chain.append(cur["_tpl"])
            cur = by_id.get(cur.get("parentId"))
        host = cur["_tpl"] if cur else None
        cost = sum(ergo(t) for t in chain)
        rows.append({
            "build": b["Name"], "optic": i["_tpl"], "chain": chain,
            "cost": cost, "host": host, "optic_ergo": ergo(i["_tpl"]),
        })

print(f"{len(rows)} builds carry an optic\n")

print("=== how much ergonomics goes on mounting hardware ===")
dist = Counter()
for r in rows:
    dist[min(len(r["chain"]), 4)] += 1
for n in sorted(dist):
    label = f"{n} part(s)" + (" or more" if n == 4 else "")
    print(f"   {dist[n]:>4} builds  {label} between optic and gun")
tot = sum(r["cost"] for r in rows)
print(f"\n   total ergonomics spent on mounts: {tot:+.0f}")
print(f"   average per optic:                {tot/max(len(rows),1):+.2f}")

print("\n=== worst: most ergonomics paid to mount a sight ===")
for r in sorted(rows, key=lambda r: r["cost"])[:8]:
    if r["cost"] >= 0:
        break
    print(f"   {r['cost']:+.0f} ergo  {r['build']}")
    print(f"        optic {nm(r['optic'])[:44]} (ergo {r['optic_ergo']:+})")
    for t in r["chain"]:
        print(f"        via   {nm(t)[:44]:<44} ergo {ergo(t):+}")

# ---------------------------------------------- was a cheaper path available?
print("\n=== could the optic have gone on directly? ===")
def accepts(host_tpl, tpl):
    for s in props(host_tpl).get("Slots", []) or []:
        if not (s.get("_name") or "").startswith(("mod_scope", "mod_sight", "mod_mount")):
            continue
        f = (s.get("_props") or {}).get("filters", [{}])[0]
        if tpl in (f.get("Filter") or []):
            return True
    return False

direct = [r for r in rows if r["chain"] and r["host"] and accepts(r["host"], r["optic"])
          and r["cost"] < 0]
print(f"   {len(direct)} builds pay for a mount chain to carry an optic the host accepts directly")
for r in direct[:8]:
    print(f"      {r['cost']:+.0f} ergo  {r['build']}  -  {nm(r['optic'])[:38]}")
    print(f"               on {nm(r['host'])[:50]}")

# ---------------------------------------------- overhead vs what the sight gives
print("\n=== mounting overhead against the sight it carries ===")
worst = [r for r in rows if r["cost"] < 0]
by_optic = defaultdict(list)
for r in worst:
    by_optic[nm(r["optic"])].append(r["cost"])
print(f"   {len(worst)} of {len(rows)} optics cost ergonomics to mount")
for n, cs in sorted(by_optic.items(), key=lambda kv: sum(kv[1]))[:8]:
    print(f"      {sum(cs):+6.0f} total over {len(cs):>3} builds   {n[:46]}")
