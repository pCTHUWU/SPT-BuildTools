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
import collections, json, io, os, sys
from options import OPT, ITEMS, resolve_profile
from buildlib import (db, loc, name, new_id, categories, conflicts, loyalty, buyable_now,
                      dominates, pareto_front, _knee)

PROF = resolve_profile()
INVENTORY = "55d7217a4bdc2d86028b456d"    # Default Inventory - the root every loadout hangs off
TAG = "(kit)"

# Worn slots worth optimising. Weapons belong to the other generators; Dogtag and ArmBand are
# cosmetic; Pockets is fixed by the profile and not a choice.
# SecuredContainer is deliberately absent. You always have one, they are not purchasable, and
# including it put an unbuyable "Secure container Beta" in every kit - which then showed as NOT
# AVAILABLE on the buy-parts screen and in anything trying to restock the kit.
WORN = ["Headwear", "Earpiece", "FaceCover", "Eyewear", "ArmorVest", "TacticalVest",
        "Backpack", "Scabbard"]

# Necessary gear: filled whatever it scores. A headset protects nothing and carries nothing, so on
# the four axes it reads as pure weight and the generator dropped it from every loadout - the same
# shape as the bare plate carrier scoring negative.
# ArmorVest is in the list but still yields to an armoured rig - the plates are then in the rig.
ESSENTIAL = {"Earpiece", "Headwear", "TacticalVest", "Backpack", "ArmorVest"}

# What a headset is *for* is hearing range, and the database does not carry it: all 15 read
# AmbientVolume -50 and DryVolume -60, the real differences being compressor and EQ curves that do
# not reduce to a number. Scoring on the numbers that *are* present meant scoring on weight.
#
# Sprint hearing distance in metres, from the official wiki's Earpieces table
# (escapefromtarkov.fandom.com/wiki/Earpieces). Stated policy from a cited source, the way
# optic_rank encodes an optic preference - not a derived stat, and not guesswork.
#
# Worth keeping the numbers rather than tiers: a tier-list article consulted first had the Safariland
# Liberator as poor (it is 66m, near the top), the GSSh-01 as "barely better than nothing" (62m,
# mid-pack), and the ComTac II as solid (60m, below the GSSh). Wearing nothing at all is 53m, so
# the whole spread is 14m and the bottom few headsets are worth very little over bare ears.
#
# Order matters - "ComTac V" is a prefix of "ComTac VI", so VI is tested first.
NO_EARPIECE_RANGE = 53
HEADSET_RANGE = [("ComTac VI", 67), ("ComTac V", 67), ("ComTac IV", 66),
                 ("Liberator", 66), ("FAST RAC", 66),
                 ("XCEL", 63), ("Sordin", 63), ("Tactical Sport", 63),
                 ("GSSh", 62), ("Earmor M32", 61), ("ComTac II", 60),
                 ("Razor", 59), ("ProFlex", 59), ("TEP-300", 54)]

def hearing(tpl):
    """Sprint hearing distance in metres. Unknown headsets fall back to bare ears rather than an
    optimistic guess - a headset nobody has measured should not win on assumption."""
    n = (name(tpl) or "").lower()
    # Longest fragment first. "ComTac V" is a substring of "ComTac VI", so plain list order only
    # works while VI happens to sit above V - reorder the table and every ComTac VI silently
    # matches V instead. Both read 67m today, so this costs nothing now and stops a later edit
    # introducing a wrong number quietly. GearTierColors guards the same collision the same way.
    for frag, m in sorted(HEADSET_RANGE, key=lambda fm: -len(fm[0])):
        if frag.lower() in n:
            return m
    return NO_EARPIECE_RANGE

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


# The highest armour class a player can actually obtain. Above this is boss or dev kit - the
# development balaclava reads class 10 at 0.1kg while covering no zones at all, so it is the best
# armour-per-gram in the database and wins outright the moment a build is allowed to reach it.
# kit_audit uses the same number; it is defined here so there is one of it.
ARMOUR_SANITY = 6

_priced = None
def priced(tpl):
    """Does the game put a handbook price on this? Loaded lazily so import order cannot bite."""
    global _priced
    if _priced is None:
        hb_path = os.path.join(os.path.dirname(ITEMS), "handbook.json")
        _priced = {i["Id"] for i in json.load(io.open(hb_path, encoding="utf-8")).get("Items", [])}
    return tpl in _priced


def usable(tpl):
    it = db.get(tpl)
    if not it or not it.get("_props") or it["_props"].get("QuestItem"):
        return False
    p = it["_props"]
    # Dev and event kit that would win every axis at once. The 300-cell endless backpack is the
    # obvious one; anything unobtainable is a build nobody can actually assemble.
    if p.get("CanSellOnRagfair") is False and tpl not in loyalty:
        return False
    # Two holes that only opened once the meta tier stopped filtering by loyalty, and that name
    # matching cannot close: "Fischer Development" is a real manufacturer and "DevTac" a real brand,
    # while the worst offender - `endlessBackpack`, 300 cells at 1.2kg - is dressed up as a
    # "Mystery Ranch Terraplane backpack" and matches nothing.
    #
    # The game never gives it a handbook price, which is the honest tell.
    if not priced(tpl):
        return False
    # And class 10 on a 0.1kg face cover is not gear, whatever the flea flag says.
    if num(p.get("armorClass")) > ARMOUR_SANITY:
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

def biggest(tpl):
    """Largest single contiguous grid. Total cells alone says a rig is as useful as a backpack:
    the Crye AVS carries 23 cells but across *twelve* pouches whose largest is 2x2, so nothing
    bulky fits in any of them, while an LBT-2670 puts 48 in one 6x8 that takes almost anything.
    Cells say what you can carry; this says what shape it can be."""
    return max((num(g["_props"].get("cellsH")) * num(g["_props"].get("cellsV"))
                for g in (db[tpl]["_props"].get("Grids") or [])), default=0)

def footprint(tpl):
    """The space the item itself occupies. A container earns its place when it holds more than it
    takes up - the usual EFT judgement on cases. Worn kit does not occupy grid space, so this only
    bites for anything nested inside something else."""
    p = db[tpl]["_props"]
    return num(p.get("Width")) * num(p.get("Height"))

def net_cells(tpl):
    return storage(tpl) - footprint(tpl)

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

# Armour slots are zones. What class you are "rated at" is what covers the vitals; a groin insert
# matters, but it is not what stops the round through your chest. Coverage of the rest is reported
# separately rather than folded into the class, so neither hides the other.
VITAL = {"Front_plate", "Back_plate", "Soft_armor_front", "Soft_armor_back", "Helmet_top"}

def rated_class(items):
    """Highest class over the vital zones, falling back to the best worn if none are filled."""
    vit = [armor(i["_tpl"]) for i in items[1:] if i.get("slotId") in VITAL]
    return max(vit) if vit else max((armor(i["_tpl"]) for i in items[1:]), default=0)

def coverage(items):
    """How many armour zones are covered at all - the breadth the class number cannot show."""
    return sum(1 for i in items[1:] if armor(i["_tpl"]) > 0)


def useful_space(cells, big):
    """Cells you can actually use. Half-weighting the largest grid rewards one big pocket over the
    same count split into many small ones, without pretending the small ones are worthless."""
    return cells + 0.5 * big

def score(tpl, w):
    wa, ws, wm = w
    return (wa * armor(tpl) + ws * useful_space(storage(tpl), biggest(tpl))
            - wm * (weight(tpl) + penalty(tpl) / 10.0))

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
    a, s, big = armor(tpl), storage(tpl), biggest(tpl)
    wt, pen = weight(tpl), penalty(tpl)
    if depth < 3:
        for slot in db[tpl]["_props"].get("Slots", []) or []:
            best, best_v = None, 0.0
            for c in expand(slot["_props"]["filters"][0]["Filter"]):
                if not usable(c):
                    continue
                ca, cs, cbig, cwt, cpen = potential(c, w, depth + 1)
                v = wa * ca + ws * useful_space(cs, cbig) - wm * (cwt + cpen / 10.0)
                if v > best_v:
                    best, best_v = (ca, cs, cbig, cwt, cpen), v
            if best:
                # Armour and pocket size take the max - a second class-4 plate and a second small
                # pouch each add nothing you did not have. Cells, weight and penalty accumulate.
                a = max(a, best[0]); s += best[1]; big = max(big, best[2])
                wt += best[3]; pen += best[4]
    _pot[key] = (a, s, big, wt, pen)
    return _pot[key]

def reach(tpl, w):
    wa, ws, wm = w
    a, s, big, wt, pen = potential(tpl, w)
    return wa * a + ws * useful_space(s, big) - wm * (wt + pen / 10.0)


def kit_stats(items):
    """Protection, storage, weight, penalty for a finished loadout.

    Protection is the **highest** class worn, not the sum of every plate. Summing rewarded
    stacking - the first version fitted eleven plates into one vest and called 31.9kg a good
    loadout - in exactly the way summing ergonomics rewarded four mount plates under one scope.
    You are rated at the class covering you, so that is what the axis measures; the weight and
    penalty axes then push toward the lightest way to reach it, which is how the real meta works
    (a Slick is chosen for costing nothing, and the plates do the protecting).
    """
    s = big = wt = pen = 0
    for i in items[1:]:
        s += storage(i["_tpl"]); big = max(big, biggest(i["_tpl"]))
        wt += weight(i["_tpl"]); pen += penalty(i["_tpl"])
    return rated_class(items), s, big, round(wt, 2), round(pen, 1)


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
        must = s["_required"] or (top and nm in ESSENTIAL)
        if nm == "Earpiece":
            # Hearing first, weight only to break a tie. Every other axis is blind to what a
            # headset does, so leaving this to reach() picks the lightest and calls it best.
            best = max(cands, key=lambda c: (hearing(c), -weight(c)))
        else:
            # Judge on what the piece is worth once filled, not bare - see reach().
            best = max(cands, key=lambda c: reach(c, w))
        if not must and reach(best, w) <= 0:
            continue
        # You are rated at the class covering you, so a plate no better than what is already on
        # buys nothing and weighs something. This model has no zone coverage, so it cannot tell a
        # side plate from a redundant front one - it errs toward the lighter kit rather than
        # hanging ten plates on a carrier, which is the failure it replaces.
        # No "skip a plate no better than what is already worn" rule here, though an earlier
        # version had one. Armour slots are *zones* - Front_plate, Groin, Soft_armor_back,
        # Helmet_ears - so a class-3 groin insert under a class-5 front plate is not redundant,
        # it is the only thing covering the groin. That rule denied real coverage. Over-armouring
        # is held in check by the weight and penalty axes instead, which is where it belongs.
        fill(best, node["_id"], nm, depth + 1, placed, w, level, out)


def make(level):
    variants = []
    for w in WEIGHT_SWEEP:
        items, placed = [], set()
        fill(INVENTORY, None, None, 0, placed, w, level, items, top=True)
        a, s, big, wt, pen = kit_stats(items)
        # Weight and penalty are one axis, not two. As separate axes they both push the same way,
        # so mobility counted double against protection and the knee picked a class 2 loadout at
        # loyalty 2. They are the same currency to the player - the comment on WEIGHT_SWEEP said so
        # already - and the score() term combines them the same way.
        variants.append(((a, useful_space(s, big), -(wt + pen / 10.0)), (items, w)))
    front = pareto_front(variants) or variants
    return _knee(front)[1][0]


def label(items):
    a, s, big, wt, pen = kit_stats(items)
    return (f"class {a:>3.0f}  zones {coverage(items):>2}  cells {s:>3.0f} (largest {big:>2.0f})  "
            f"weight {wt:>6.2f}kg  penalty {pen:>5.1f}")


# None means no loyalty filter at all - best in slot from everything obtainable, the equipment
# equivalent of the weapon generator's (meta) builds. fill() already honours it; nothing ever
# passed it. Flea-only gear is fair game here, which is the whole point: a meta loadout assumes
# max standing and full availability, exactly as the weapon meta builds do.
levels = ([None, 1, 2, 3, 4] if "--all" in sys.argv else [None])
builds = []
for lvl in levels:
    items = make(lvl)
    tier_name = "meta" if lvl is None else f"loyalty lvl {lvl}"
    builds.append({"Id": new_id(), "Name": f"kit - {tier_name} {TAG}",
                   "Root": items[0]["_id"], "Items": items, "BuildType": "Custom"})
    worn = [i for i in items if i.get("parentId") == items[0]["_id"]]
    buy = sum(1 for i in items[1:] if buyable_now(i["_tpl"]))
    print(f"  {tier_name:<14}: {len(items)-1:>2} pieces  {label(items)}   "
          f"{buy} buyable now")
    for i in worn:
        kids = [k for k in items if k.get("parentId") == i["_id"]]
        extra = f"  + {len(kids)} plate(s)" if kids else ""
        # Net cells only means anything for something that occupies space to give space. Worn kit
        # does not, so it is shown for information rather than scored - it becomes a real axis if
        # this ever starts packing cases inside the bag.
        if storage(i["_tpl"]):
            extra += (f"  [{storage(i['_tpl']):.0f} cells, largest {biggest(i['_tpl']):.0f},"
                      f" net {net_cells(i['_tpl']):+.0f}]")
        print(f"        {i['slotId']:<17} {name(i['_tpl'])[:40]}{extra}")

if "--write" in sys.argv:
    prof = json.load(io.open(PROF, encoding="utf-8"))
    kept = [b for b in prof["userbuilds"]["equipmentBuilds"] if TAG not in (b.get("Name") or "")]
    prof["userbuilds"]["equipmentBuilds"] = kept + builds
    with io.open(PROF, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nWritten. kept {len(kept)} existing, added {len(builds)}.")
else:
    print("\n(preview only - pass --write to save)")
