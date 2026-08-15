"""Shared machinery for the build generators.

`make_builds.py` and `make_loyalty_builds.py` were near-duplicates, so every fix had to be applied
twice and a third generator would have made that permanent. This holds the parts that are
character-identical between them: the item database, the category constants, and the helpers that
do not depend on anything either generator specialises.

What is deliberately NOT here: `grow`, `narrow`, `pick`, `refine`, `score`, `compatible`, `usable`
and friends. Those differ because the loyalty generator threads a trader level through them.
Unifying those is a separate job with real regression risk; this module is the part that carries
none.
"""
import collections, json, os, random
from options import OPT, ITEMS, LOCALE, DB_DIR, resolve_profile

db  = json.load(open(ITEMS,  encoding="utf-8"))
loc = json.load(open(LOCALE, encoding="utf-8"))

# ---- trader availability. Which loyalty level each item first appears at, and what the player can
# actually buy right now at their own standing. Shared so every generator answers this the same way.

loyalty = {}                                   # tpl -> lowest loyalty level any trader sells it at
by_trader = collections.defaultdict(dict)      # tpl -> {trader: level}
for _t in os.listdir(f"{DB_DIR}/traders"):
    _p = f"{DB_DIR}/traders/{_t}/assort.json"
    if not os.path.exists(_p):
        continue
    _a = json.load(open(_p, encoding="utf-8"))
    _ll = _a["loyal_level_items"]
    for _it in _a["items"]:
        if _it.get("parentId") != "hideout":   # only top-level offers are purchasable
            continue
        _lvl = _ll.get(_it["_id"])
        if _lvl is None:
            continue
        _tpl = _it["_tpl"]
        if _tpl not in loyalty or _lvl < loyalty[_tpl]:
            loyalty[_tpl] = _lvl
        _cur = by_trader[_tpl].get(_t)
        if _cur is None or _lvl < _cur:
            by_trader[_tpl][_t] = _lvl

_prof = json.load(open(resolve_profile(), encoding="utf-8"))
STANDING = {tid: (i.get("loyaltyLevel") or 0)
            for tid, i in _prof["characters"]["pmc"]["TradersInfo"].items()
            if i.get("unlocked")}

def buyable_now(tpl):
    """Can the player buy this at their current standing, from any unlocked trader?"""
    return any(STANDING.get(t, 0) >= lvl for t, lvl in by_trader.get(tpl, {}).items())

OPTIC_CATS = ("Collimator", "CompactCollimator", "OpticScope", "AssaultScope", "SpecialScope")

# CombTactical and LaserDesignator are empty categories in this database - the light/laser combos
# (AN/PEQ-15 and friends) are all TacticalCombo, and there are only 3 plain Flashlights.
LIGHT_CATS = ("Flashlight", "TacticalCombo")

SHORT_CAL = {"Caliber9x19PARA", "Caliber9x18PM", "Caliber9x21", "Caliber1143x23ACP",
             "Caliber762x25TT", "Caliber57x28", "Caliber46x30", "Caliber12g", "Caliber20g",
             "Caliber23x75", "Caliber366TKM", "Caliber127x33"}

LONG_CAL = {"Caliber762x51", "Caliber762x54R", "Caliber86x70", "Caliber127x55", "Caliber9x39"}

LOOKAHEAD  = 4      # how far to search for a sight when judging a route

NOT_MOUNTING = ("Silencer", "Barrel", "Receiver", "Handguard", "GasBlock", "Stock",
                "PistolGrip", "Magazine", "Foregrip", "Bipod", "Flashlight", "TacticalCombo")

_SLOT_RANK = {"mod_pistol_grip": 9}

EARNS_PLACE = ("Collimator", "CompactCollimator", "OpticScope", "AssaultScope", "SpecialScope",
               "Flashlight", "TacticalCombo", "Silencer", "Magazine", "Stock", "Foregrip",
               "IronSight", "Barrel", "Receiver", "Handguard", "GasBlock",
               "PistolGrip", "ChargingHandle", "Launcher", "GrenadeLauncher")

_conf = {}

_cat = {}

def new_id(_used=set()):
    while True:
        i = "".join(random.choice("0123456789abcdef") for _ in range(24))
        if i not in _used:
            _used.add(i); return i

def name(tpl):
    return loc.get(f"{tpl} Name") or db.get(tpl, {}).get("_name", tpl)

def categories(tpl):
    if tpl not in _cat:
        out, cur, n = [], db.get(tpl), 0
        while cur and n < 14:
            out.append(cur.get("_name") or "")
            cur = db.get(cur.get("_parent")); n += 1
        _cat[tpl] = out
    return _cat[tpl]

def conflicts(tpl):
    if tpl not in _conf:
        it = db.get(tpl) or {}
        _conf[tpl] = frozenset((it.get("_props") or {}).get("ConflictingItems") or [])
    return _conf[tpl]

def slot_rank(n):
    if (n or "").startswith("mod_stock"):
        return 0
    return _SLOT_RANK.get(n, 5)

def slot_required(parent_tpl, slot_name):
    for s in (db.get(parent_tpl, {}).get("_props") or {}).get("Slots", []) or []:
        if s.get("_name") == slot_name:
            return bool(s.get("_required"))
    return False

def is_optic(tpl):
    return any(c in categories(tpl) for c in OPTIC_CATS)

def is_light(tpl):
    return any(c in categories(tpl) for c in LIGHT_CATS)

def is_combo(tpl):
    return "TacticalCombo" in categories(tpl)

def is_magazine(tpl):
    return "Magazine" in categories(tpl)

def is_suppressor(tpl):
    return "Silencer" in categories(tpl)

def is_mounting_part(tpl):
    c = categories(tpl)
    if any(x in c for x in NOT_MOUNTING) or is_optic(tpl):
        return False
    return "Mount" in c or "MountsAndAdapters" in c

def is_stock_slot(s):
    """A slot holding an actual shoulder stock, not a butt pad or cheek rest.

    Needs BOTH tests. The name alone is not enough: a butt pad slot on a wooden AK stock is also
    called mod_stock, and its one candidate cuts recoil by 1. The recoil test alone is far worse -
    muzzle brakes, compensators and suppressors all cut recoil by 15+, so testing recoil on its own
    quietly made every muzzle must-fill and forced 27 conflicting muzzle devices into builds.
    """
    if not (s.get("_name") or "").startswith("mod_stock"):
        return False
    f = (s.get("_props") or {}).get("filters", [{}])[0]
    return any((((db.get(c) or {}).get("_props") or {}).get("Recoil", 0) or 0) <= -5
               for c in (f.get("Filter", []) or []))

def mag_slots(tpl):
    """Grid footprint. A standard rifle magazine is 1x2; drums and long extendeds are 1x3 or 2x2."""
    p = db.get(tpl, {}).get("_props") or {}
    return (p.get("Width") or 0) * (p.get("Height") or 0)

def _mag_footprint(its):
    return max((mag_slots(i["_tpl"]) for i in its if is_magazine(i["_tpl"])), default=0)

def optic_policy(weapon_tpl):
    cal = (db[weapon_tpl]["_props"].get("ammoCaliber") or "")
    if cal in SHORT_CAL:
        return "reddot"
    if cal in LONG_CAL:
        return "long"
    return "lpvo"

def earns_place(tpl, weapon_tpl=None):
    c = categories(tpl)
    if "Bipod" in c:
        # A bipod earns its place on a gun fired from a rest - a bolt-action, a marksman rifle,
        # a machine gun. On an SMG or a carbine it is weight and a worse ergonomics score.
        if weapon_tpl is None:
            return True
        wp = db.get(weapon_tpl, {}).get("_props") or {}
        fire = set(wp.get("weapFireType") or [])
        if "MachineGun" in categories(weapon_tpl):
            return True
        if (wp.get("ammoCaliber") or "") in LONG_CAL:
            return True
        return not (fire & {"fullauto", "burst"})
    return any(x in c for x in EARNS_PLACE)

def prune_empty(items):
    """Drop parts that ended up carrying nothing and giving nothing.

    Filling is depth-first, so whether a rail earns its place is not knowable until its children
    have been tried - and 413 of them ended up holding air, an Aimpoint spacer with no Aimpoint on
    it 258 times over. This is the same habit that hung a grenade launcher under 57 builds: a slot
    that can be filled is not a slot worth filling.

    Runs to a fixed point, because removing a leaf can leave its parent holding nothing in turn.
    Required slots, and anything with a real job, are left alone.
    """
    if not OPT["prune-empty"]:
        return items
    weapon_tpl = items[0]["_tpl"] if items else None
    while True:
        kids = set(i.get("parentId") for i in items if i.get("parentId"))
        by_id = {i["_id"]: i for i in items}
        drop = None
        for i in items:
            if not i.get("parentId") or i["_id"] in kids:
                continue
            tpl = i["_tpl"]
            if earns_place(tpl, weapon_tpl):
                continue
            p = db.get(tpl, {}).get("_props") or {}
            if (p.get("Ergonomics", 0) or 0) > 0 or (p.get("Recoil", 0) or 0) < 0:
                continue          # pays for itself on one axis or the other
            parent = by_id.get(i["parentId"])
            if parent and slot_required(parent["_tpl"], i.get("slotId")):
                continue
            drop = i
            break
        if drop is None:
            return items
        items.remove(drop)

def short_name(tpl):
    return loc.get(f"{tpl} ShortName") or name(tpl)

def weapon_is_auto(tpl):
    """Does this weapon hold the trigger down? Read from its fire modes, the one source of truth."""
    return bool(set(db[tpl]["_props"].get("weapFireType") or []) & {"fullauto", "burst"})

def dominates(a, b):
    """Three axes: ergonomics up, accuracy up, vertical recoil down. `a` dominates `b` if it is no
    worse on any of them and better on at least one."""
    return all(x >= y for x, y in zip(a[:2], b[:2])) and a[2] <= b[2] \
        and (a[0] > b[0] or a[1] > b[1] or a[2] < b[2])

def pareto_front(points):
    return [p for i, p in enumerate(points)
            if not any(dominates(q[0], p[0]) for j, q in enumerate(points) if j != i)]

def _knee(pool):
    """The point closest to the ideal corner once each axis is normalised over the pool."""
    es = [p[0][0] for p in pool]
    ac = [p[0][1] for p in pool]
    rc = [p[0][2] for p in pool]

    def norm(v, lo, hi, invert=False):
        if hi == lo:
            return 1.0
        t = (v - lo) / (hi - lo)
        return 1 - t if invert else t

    return max(pool, key=lambda p: norm(p[0][0], min(es), max(es))
                                 + norm(p[0][1], min(ac), max(ac))
                                 + norm(p[0][2], min(rc), max(rc), invert=True))
