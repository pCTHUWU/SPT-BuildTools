"""Count sights and light sources per build, before and after the stat optimisation."""
import io, json, sys
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from options import ITEMS, resolve_profile
from collections import Counter

ITEMS = ITEMS
NOW = resolve_profile()
items = json.load(io.open(ITEMS, encoding="utf-8"))

def chain(tpl):
    out, cur, n = [], items.get(tpl), 0
    while cur and n < 14:
        out.append(cur.get("_name") or "")
        cur = items.get(cur.get("_parent")); n += 1
    return out

_c = {}
def cat(tpl):
    if tpl not in _c:
        _c[tpl] = chain(tpl)
    return _c[tpl]

def is_sight(t):
    c = cat(t)
    return any(x in c for x in ("CompactCollimator", "Collimator", "OpticScope",
                                "AssaultScope", "SpecialScope"))
def is_iron(t):
    c = cat(t)
    return any(x in c for x in ("IronSight",))
def is_light(t):
    c = cat(t)
    return any(x in c for x in ("Flashlight", "TacticalCombo", "CombTactical"))
def is_laser(t):
    return "LaserDesignator" in cat(t)

def report(path, label):
    prof = json.load(io.open(path, encoding="utf-8"))
    wb = prof["userbuilds"]["weaponBuilds"]
    sights = Counter(); lights = 0; nolight = 0; multi = 0
    worst = []
    for b in wb:
        s = sum(1 for i in b["Items"] if is_sight(i["_tpl"]))
        l = sum(1 for i in b["Items"] if is_light(i["_tpl"]) or is_laser(i["_tpl"]))
        sights[s] += 1
        if l:
            lights += 1
        else:
            nolight += 1
        if s > 1:
            multi += 1
            worst.append((s, b["Name"]))
    print(f"{label}  ({len(wb)} builds)")
    print(f"   sights per build : " + ", ".join(f"{k}->{v}" for k, v in sorted(sights.items())))
    print(f"   builds with >1 sight : {multi} ({multi*100//len(wb)}%)")
    print(f"   builds with a light/laser : {lights}   without : {nolight} ({nolight*100//len(wb)}%)")
    worst.sort(reverse=True)
    for n, name in worst[:4]:
        print(f"      {n} sights: {name}")
    print()

report(sys.argv[1] if len(sys.argv) > 1 else NOW, "CURRENT")
report(NOW + ".bak-preStatOpt", "before stat optimisation")
report(NOW + ".bak-preConflictFix", "before conflict fix (original)")
