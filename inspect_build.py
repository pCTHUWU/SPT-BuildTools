"""Dump one build as a tree and confirm the conflicts are real, from both directions."""
import io, json, sys

PROFILE = r"C:\SPT\SPT_Runtime\user\profiles\6a751c000164cc5fb0ccc217.json"
ITEMS   = r"C:\SPT\SPT_Runtime\SPT_Data\database\templates\items.json"

items = json.load(io.open(ITEMS, encoding="utf-8"))
prof  = json.load(io.open(PROFILE, encoding="utf-8"))
target = sys.argv[1]

def nm(t):
    it = items.get(t)
    return (it.get("_name") if it else None) or t

b = next(x for x in prof["userbuilds"]["weaponBuilds"] if x.get("Name") == target)
its = b["Items"]
kids = {}
for i in its:
    kids.setdefault(i.get("parentId"), []).append(i)

def walk(pid, depth):
    for i in sorted(kids.get(pid, []), key=lambda x: x.get("slotId") or ""):
        print("   " * depth + f"{i.get('slotId') or '(root)'}: {nm(i['_tpl'])}")
        walk(i["_id"], depth + 1)

print(f"=== {target} ===  ({len(its)} parts)")
walk(None, 0)

print("\n=== conflict check, both directions ===")
tpls = [i["_tpl"] for i in its]
seen = set()
for a in tpls:
    ca = set((items.get(a, {}).get("_props", {}) or {}).get("ConflictingItems", []) or [])
    for bb in tpls:
        if bb == a or bb not in ca:
            continue
        pair = tuple(sorted((a, bb)))
        if pair in seen:
            continue
        seen.add(pair)
        cb = set((items.get(bb, {}).get("_props", {}) or {}).get("ConflictingItems", []) or [])
        print(f"\n{nm(a)}")
        print(f"   lists {nm(bb)} in its ConflictingItems : True")
        print(f"   and the reverse is listed too          : {a in cb}")
        # where does each sit?
        for t in (a, bb):
            for i in its:
                if i["_tpl"] == t:
                    par = next((x for x in its if x["_id"] == i.get("parentId")), None)
                    print(f"   {nm(t):<58} in slot '{i.get('slotId')}' of {nm(par['_tpl']) if par else '(root)'}")
