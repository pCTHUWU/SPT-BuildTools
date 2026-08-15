"""Generate meta equipment loadouts for the SPT profile.

The same idea as the weapon generators, applied to what the player wears. Two things differ:

* **Equipment slot filters name base *classes*, not items.** `Headwear` lists the node `Headwear`,
  not 111 helmets, so every filter has to be expanded to its descendants first.
* **Armour is plate-based.** Carriers have `armorClass = 0` and plate slots; the plates carry the
  class. So a loadout is a nested tree exactly like a weapon, and the same grow/narrow shape works.

Four axes, because that is what the meta actually trades: protection, storage, weight and the
handling penalties. Pareto over the four, then the knee - one fixed weighting would bake the same
compromise into a scav run and a raid kit, and it is the wrong one for both.

Preview by default; pass --write to save.  --all writes one loadout per loyalty tier.
"""
import collections, json, io, sys
from options import OPT, resolve_profile
from buildlib import (db, loc, name, new_id, categories, conflicts, loyalty, buyable_now,
                      dominates, pareto_front, _knee)

PROF = resolve_profile()
INVENTORY = "55d7217a4bdc2d86028b456d"    # Default Inventory - the root every loadout hangs off
TAG = "(kit)"

# Worn slots worth optimising. Weapons belong to the other generators; Dogtag and ArmBand are
# cosmetic; Pockets is fixed by the profile and not a choice.
WORN = ["Headwear", "Earpiece", "FaceCover", "Eyewear", "ArmorVest", "TacticalVest",
        "Backpack", "SecuredContainer", "Scabbard"]

# Weightings swept over (protection, storage, mobility). Mobility covers weight and the movement,
# turn and ergonomics penalties together - they are the same currency to the player.
WEIGHT_SWEEP = [(2.0, 0.5, 1.0),    # armoured push
                (1.0, 1.0, 1.0),    # balanced
                (0.5, 1.5, 1.0),    # hauler
                (0.5, 0.5, 2.0)]    # light and fast


def descendants(node, out=None):
    """Concrete items under a base class. Equipment filters name the class, not the items."""
    out = [] if out is None else out
    for k, v in db.items():
        if v.get("_parent") == node:
            if v.get("_type") == "Item":
                out.append(k)
            descendants(k, out)
    return out

_expanded = {}
def expand(filt):
    key = tuple(filt)
    if key not in _expanded:
        got = []
        for c in filt:
            e = db.get(c)
            if not e:
                continue
            got.append(c) if e.get("_type") == "Item" else got.extend(descendants(c))
        _expanded[key] = got
    return _expanded[key]


def usable(tpl):
    it = db.get(tpl)
    if not it or not it.get("_props") or it["_props"].get("QuestItem"):
        return False
    p = it["_props"]
    # Dev and event kit that would win every axis at once. The 300-cell endless backpack is the
    # obvious one; anything unobtainable is a build nobody can actually assemble.
    if p.get("CanSellOnRagfair") is False and tpl not in loyalty:
        return False
    return True


def num(v):
    """Equipment stats are not consistently typed in this database - `armorClass` is a string on
    727 items and an int on 67. Reading it raw multiplies a str by a float and dies, or worse
    compares '10' < '9'. Everything numeric goes through here."""
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0

def storage(tpl):
    return sum(num(g["_props"].get("cellsH")) * num(g["_props"].get("cellsV"))
               for g in (db[tpl]["_props"].get("Grids") or []))

def weight(tpl):
    return num(db[tpl]["_props"].get("Weight"))

def penalty(tpl):
    """Movement, turn and ergonomics costs. Stored negative; returned as a positive cost."""
    p = db[tpl]["_props"]
    return -(num(p.get("speedPenaltyPercent"))
             + num(p.get("mousePenalty"))
             + num(p.get("weaponErgonomicPenalty")))

def armor(tpl):
    return num(db[tpl]["_props"].get("armorClass"))


def score(tpl, w):
    wa, ws, wm = w
    return wa * armor(tpl) + ws * storage(tpl) - wm * (weight(tpl) + penalty(tpl) / 10.0)

_pot = {}
def potential(tpl, w, depth=0):
    """(armour, storage, weight, penalty) this piece reaches once sensibly filled.

    A plate carrier is the equipment version of a scope mount: `armorClass = 0`, no storage, some
    weight, so judged alone it scores negative and gets dropped for not earning its place. That is
    exactly what happened - the first run fitted no helmet, no body armour and no plates at all,
    and took its only protection from a face mask. Its worth is the plates it can carry, so look
    ahead the way optic_reach does for sights.

    The axes combine the way they do in reality, which is the fix for the second round of this
    bug: **armour takes the max, everything else sums**. Summing armour made a ten-slot carrier
    outscore a four-slot one at the same class, so the optimiser hung eleven plates on one vest
    and called 31.9kg good. You are rated at the class covering you; each extra plate past that
    is only weight, and now scores as only weight.
    """
    key = (tpl, w, depth)
    if key in _pot:
        return _pot[key]
    wa, ws, wm = w
    a, s, wt, pen = armor(tpl), storage(tpl), weight(tpl), penalty(tpl)
    if depth < 3:
        for slot in db[tpl]["_props"].get("Slots", []) or []:
            best, best_v = None, 0.0
            for c in expand(slot["_props"]["filters"][0]["Filter"]):
                if not usable(c):
                    continue
                ca, cs, cwt, cpen = potential(c, w, depth + 1)
                v = wa * ca + ws * cs - wm * (cwt + cpen / 10.0)
                if v > best_v:
                    best, best_v = (ca, cs, cwt, cpen), v
            if best:
                a = max(a, best[0]); s += best[1]; wt += best[2]; pen += best[3]
    _pot[key] = (a, s, wt, pen)
    return _pot[key]

def reach(tpl, w):
    wa, ws, wm = w
    a, s, wt, pen = potential(tpl, w)
    return wa * a + ws * s - wm * (wt + pen / 10.0)


def kit_stats(items):
    """Protection, storage, weight, penalty for a finished loadout.

    Protection is the **highest** class worn, not the sum of every plate. Summing rewarded
    stacking - the first version fitted eleven plates into one vest and called 31.9kg a good
    loadout - in exactly the way summing ergonomics rewarded four mount plates under one scope.
    You are rated at the class covering you, so that is what the axis measures; the weight and
    penalty axes then push toward the lightest way to reach it, which is how the real meta works
    (a Slick is chosen for costing nothing, and the plates do the protecting).
    """
    a = s = wt = pen = 0
    for i in items[1:]:
        a = max(a, armor(i["_tpl"])); s += storage(i["_tpl"])
        wt += weight(i["_tpl"]); pen += penalty(i["_tpl"])
    return a, s, round(wt, 2), round(pen, 1)


def compatible(tpl, placed):
    if not OPT["conflicts"]:
        return True
    if conflicts(tpl) & placed:
        return False
    return not any(tpl in conflicts(p) for p in placed)


def fill(tpl, parent_id, slot_name, depth, placed, w, level, out, top=False):
    node = {"_id": new_id(), "_tpl": tpl}
    if parent_id:
        node["parentId"] = parent_id
        node["slotId"] = slot_name
    out.append(node)
    placed.add(tpl)
    if depth >= 4:
        return
    for s in db[tpl]["_props"].get("Slots", []) or []:
        nm = s["_name"]
        if top and nm not in WORN:
            continue
        # An armoured rig and body armour are not worn together - the rig already carries the
        # plates. Without this the optimiser wore both, seventeen plates between them.
        if top and nm == "ArmorVest" and any(
                db[i["_tpl"]]["_props"].get("Slots") and i.get("slotId") == "TacticalVest"
                for i in out):
            continue
        cands = [c for c in expand(s["_props"]["filters"][0]["Filter"])
                 if usable(c) and c not in placed and compatible(c, placed)]
        if level is not None:
            tier = [c for c in cands if loyalty.get(c) is not None and loyalty[c] <= level]
            cands = tier or ([] if not s["_required"] else cands)
        if not cands:
            continue
        # Judge on what the piece is worth once filled, not bare - see reach().
        best = max(cands, key=lambda c: reach(c, w))
        if not s["_required"] and reach(best, w) <= 0:
            continue
        # You are rated at the class covering you, so a plate no better than what is already on
        # buys nothing and weighs something. This model has no zone coverage, so it cannot tell a
        # side plate from a redundant front one - it errs toward the lighter kit rather than
        # hanging ten plates on a carrier, which is the failure it replaces.
        worn = max((armor(i["_tpl"]) for i in out), default=0)
        if not s["_required"] and armor(best) and armor(best) <= worn and not storage(best):
            continue
        fill(best, node["_id"], nm, depth + 1, placed, w, level, out)


def make(level):
    variants = []
    for w in WEIGHT_SWEEP:
        items, placed = [], set()
        fill(INVENTORY, None, None, 0, placed, w, level, items, top=True)
        a, s, wt, pen = kit_stats(items)
        variants.append(((a, s, -wt, -pen), (items, w)))
    front = pareto_front(variants) or variants
    return _knee(front)[1][0]


def label(items):
    a, s, wt, pen = kit_stats(items)
    return f"armor {a:>3}  storage {s:>3}  weight {wt:>6.2f}kg  penalty {pen:>6.1f}"


levels = [1, 2, 3, 4] if "--all" in sys.argv else [4]
builds = []
for lvl in levels:
    items = make(lvl)
    builds.append({"Id": new_id(), "Name": f"kit - loyalty lvl {lvl} {TAG}",
                   "Root": items[0]["_id"], "Items": items, "BuildType": "Custom"})
    worn = [i for i in items if i.get("parentId") == items[0]["_id"]]
    buy = sum(1 for i in items[1:] if buyable_now(i["_tpl"]))
    print(f"  loyalty lvl {lvl}: {len(items)-1:>2} pieces  {label(items)}   "
          f"{buy} buyable now")
    for i in worn:
        kids = [k for k in items if k.get("parentId") == i["_id"]]
        extra = f"  + {len(kids)} plate(s)" if kids else ""
        print(f"        {i['slotId']:<17} {name(i['_tpl'])[:44]}{extra}")

if "--write" in sys.argv:
    prof = json.load(io.open(PROF, encoding="utf-8"))
    kept = [b for b in prof["userbuilds"]["equipmentBuilds"] if TAG not in (b.get("Name") or "")]
    prof["userbuilds"]["equipmentBuilds"] = kept + builds
    with io.open(PROF, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nWritten. kept {len(kept)} existing, added {len(builds)}.")
else:
    print("\n(preview only - pass --write to save)")
