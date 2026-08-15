"""Separate genuinely stockless builds from optional-accessory false positives.

A butt pad slot on a complete wooden stock is not a missing stock. Distinguish by what the slot's
candidates actually do: a real stock gives a large recoil reduction, a pad or cheek rest a token
one. Threshold checked against the data below before being applied.
"""
import io, json
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from options import ITEMS, resolve_profile
from collections import Counter

ITEMS = ITEMS
NOW = resolve_profile()
items = json.load(io.open(ITEMS, encoding="utf-8"))

def nm(t):
    it = items.get(t)
    return (it.get("_name") if it else None) or t

def recoil(t):
    return ((items.get(t) or {}).get("_props") or {}).get("Recoil", 0) or 0

def stock_slots(tpl):
    it = items.get(tpl) or {}
    for s in (it.get("_props") or {}).get("Slots", []) or []:
        n = s.get("_name") or ""
        if n.startswith("mod_stock"):
            f = (s.get("_props") or {}).get("filters", [{}])[0]
            yield n, (f.get("Filter", []) or []), bool(s.get("_required"))

# --- calibrate: what recoil do candidates of each kind actually give? ---
print("calibration - recoil of candidates for a few known slots:")
byname = {v.get("_name"): k for k, v in items.items()}
for host in ("stock_ak74_izhmash_ak74_std_wood", "stock_ar15_rtm_atp_buffer_tube",
             "weapon_izhmash_akms_762x39", "stock_mk16_fn_scar_folding_stock"):
    t = byname.get(host)
    if not t:
        continue
    for n, cands, req in stock_slots(t):
        rs = sorted(recoil(c) for c in cands)
        print(f"  {host[:44]:<44} {n:<16} req={str(req):<5} recoil range {rs[0]}..{rs[-1]}")

REAL = -5   # a real stock; pads and cheek rests sit well above this

prof = json.load(io.open(NOW, encoding="utf-8"))
wb = prof["userbuilds"]["weaponBuilds"]
genuine, culprit, examples = 0, Counter(), {}
for b in wb:
    its = b["Items"]
    filled = {(i.get("parentId"), i.get("slotId")) for i in its}
    holes = []
    for i in its:
        for n, cands, req in stock_slots(i["_tpl"]):
            if (i["_id"], n) in filled:
                continue
            best = min((recoil(c) for c in cands), default=0)
            if req or best <= REAL:
                holes.append((nm(i["_tpl"]), n, req, best))
    if holes:
        genuine += 1
        for h in holes:
            culprit[(h[0], h[1], h[2])] += 1
            examples.setdefault((h[0], h[1]), b.get("Name"))

print(f"\ngenuinely stockless builds: {genuine} of {len(wb)}")
print("\nby host part / slot:")
for (host, slot, req), n in culprit.most_common(15):
    print(f"  {n:>4}x  {host[:46]:<46} {slot:<16} required={req}")
    print(f"          e.g. {examples.get((host, slot))}")
