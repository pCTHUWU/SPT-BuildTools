"""Did the stated preferences actually land? Suppressed, light/laser combo, and a sight that
suits the calibre - no zoom on pistol-calibre automatics, a toggling optic on rifles."""
import io, json
from collections import Counter

items = json.load(io.open(r"C:\SPT\SPT_Runtime\SPT_Data\database\templates\items.json", encoding="utf-8"))
prof = json.load(io.open(r"C:\SPT\SPT_Runtime\user\profiles\6a751c000164cc5fb0ccc217.json", encoding="utf-8"))

_c = {}
def cats(t):
    if t not in _c:
        o, cur, n = [], items.get(t), 0
        while cur and n < 14:
            o.append(cur.get("_name") or ""); cur = items.get(cur.get("_parent")); n += 1
        _c[t] = o
    return _c[t]

OPTIC = ("Collimator", "CompactCollimator", "OpticScope", "AssaultScope", "SpecialScope")
SHORT_CAL = {"Caliber9x19PARA","Caliber9x18PM","Caliber9x21","Caliber1143x23ACP","Caliber762x25TT",
             "Caliber57x28","Caliber46x30","Caliber12g","Caliber20g","Caliber23x75",
             "Caliber366TKM","Caliber127x33"}
LONG_CAL = {"Caliber762x51","Caliber762x54R","Caliber86x70","Caliber127x55","Caliber9x39"}

def zooms(t):
    z = (items.get(t, {}).get("_props") or {}).get("Zooms")
    f = []
    if isinstance(z, list):
        for r in z:
            f += r if isinstance(r, list) else [r]
    return sorted({float(x) for x in f if isinstance(x, (int, float))})

def has(b, pred): return any(pred(i["_tpl"]) for i in b["Items"])

wb = prof["userbuilds"]["weaponBuilds"]
sup = sum(1 for b in wb if has(b, lambda t: "Silencer" in cats(t)))
combo = sum(1 for b in wb if has(b, lambda t: "TacticalCombo" in cats(t)))
light = sum(1 for b in wb if has(b, lambda t: any(c in cats(t) for c in ("Flashlight","TacticalCombo"))))
print(f"builds: {len(wb)}")
print(f"  suppressed                 {sup:>4} ({sup*100//len(wb)}%)")
print(f"  light/laser combo fitted   {combo:>4} ({combo*100//len(wb)}%)")
print(f"  any light at all           {light:>4} ({light*100//len(wb)}%)")

# could a suppressor have been fitted at all?
def could_suppress(b):
    for i in b["Items"]:
        for s in (items.get(i["_tpl"], {}).get("_props") or {}).get("Slots", []) or []:
            if (s.get("_name") or "").startswith("mod_muzzle"):
                f = (s.get("_props") or {}).get("filters", [{}])[0]
                if any("Silencer" in cats(c) for c in (f.get("Filter") or [])):
                    return True
    return False
missed = [b["Name"] for b in wb
          if not has(b, lambda t: "Silencer" in cats(t)) and could_suppress(b)]
print(f"  not suppressed but could be {len(missed):>3}")
for n in missed[:5]:
    print(f"       {n}")

print("\noptic choice by calibre class:")
buckets = Counter()
for b in wb:
    root = next(i for i in b["Items"] if i.get("parentId") is None)
    cal = (items[root["_tpl"]]["_props"].get("ammoCaliber") or "")
    kind = "short" if cal in SHORT_CAL else ("long" if cal in LONG_CAL else "rifle")
    op = [i["_tpl"] for i in b["Items"] if any(c in cats(i["_tpl"]) for c in OPTIC)]
    if not op:
        buckets[(kind, "no optic")] += 1
        continue
    z = zooms(op[0])
    if len(z) > 1:
        buckets[(kind, f"variable {z[0]:g}-{z[-1]:g}x")] += 1
    elif z and max(z) > 1:
        buckets[(kind, f"fixed {max(z):g}x")] += 1
    else:
        buckets[(kind, "non-magnified")] += 1
for kind in ("short", "rifle", "long"):
    rows = [(k[1], v) for k, v in buckets.items() if k[0] == kind]
    tot = sum(v for _, v in rows)
    print(f"  {kind:<6} ({tot} builds)")
    for what, n in sorted(rows, key=lambda r: -r[1])[:5]:
        print(f"      {n:>4}  {what}")
