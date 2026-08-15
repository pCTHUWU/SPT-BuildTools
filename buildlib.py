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

# How many mounting parts a sight is worth. Two adapters to reach a scope is a mount;
# four is a tower, and the ergonomics score rewards building one because plates read
# positive. Enforced always, not only when short-mounts is on - it used to sit behind
# that toggle, which made three separate fixes read byte-identical because none ran.
MAX_MOUNTS = 2

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
_zoom = {}

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

# Whether the weapon currently being built is automatic. shape_ok needs it and shape_ok lives
# here, so the state lives here too - split across modules it was a NameError waiting to happen.
# Set through the function rather than by assigning the attribute from outside, so the write is
# visible in the caller and greppable.
AUTO = False


def set_auto(value):
    global AUTO
    AUTO = bool(value)


def is_auto():
    """Read the weapon, never the weighting.

    This used to infer it from the weight tuple - `w[1] > w[0]` - which held only while
    weapon_weights was the sole producer of those tuples. The Pareto sweep feeds (1.4, 1.4) and
    (1.8, 0.8) to genuine automatics, both of which read as semi-auto, so two candidates in every
    three silently lost the magazine capacity rule and reached for a 10-round PMAG.
    """
    return AUTO


# Which sight class this weapon wants, set per build. Lives here because narrow() does; splitting
# the state from its only reader is how _zoom and is_auto both broke during this move.
POLICY = "lpvo"


def set_policy(value):
    global POLICY
    POLICY = value


def weapon_is_auto(tpl):
    """Does this weapon hold the trigger down? Read from its fire modes, the one source of truth."""
    return bool(set(db[tpl]["_props"].get("weapFireType") or []) & {"fullauto", "burst"})

def dominates(a, b):
    """`a` dominates `b` if it is no worse on any axis and better on at least one.

    **Every axis is "higher is better".** Callers negate anything they want minimised. This used to
    hardcode "first two up, third down", which silently mismeasured any caller with a different
    shape: the equipment generator passes four already-negated axes, so the third (negative weight)
    was being treated as minimise-me and the knee preferred *heavier* loadouts, while the fourth
    was ignored entirely. One convention, applied to any number of axes, cannot drift like that.
    """
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))

def pareto_front(points):
    return [p for i, p in enumerate(points)
            if not any(dominates(q[0], p[0]) for j, q in enumerate(points) if j != i)]

def _knee(pool):
    """The point closest to the ideal corner once each axis is normalised over the pool.

    Same convention as dominates(): every axis is higher-is-better, and it works for any number of
    them. The previous version read exactly three and inverted the third by name, which is how the
    equipment generator ended up chasing weight.
    """
    n = len(pool[0][0])
    cols = [[p[0][i] for p in pool] for i in range(n)]

    def norm(v, lo, hi):
        return 1.0 if hi == lo else (v - lo) / (hi - lo)

    return max(pool, key=lambda p: sum(norm(p[0][i], min(cols[i]), max(cols[i]))
                                       for i in range(n)))


# ---------------------------------------------------------------------------------------
# Moved out of the two weapon generators, where each of these existed twice. Their behaviour
# was proven identical by AST comparison first; the copies had drifted only in variable names
# and docstring wording. That drift was harmless, but the duplication was not - a fix had to
# land in two files every time, and at least once it landed in only one.
# ---------------------------------------------------------------------------------------

WEAPON_BASE = "5422acb9af1c889c16000029"   # Weapon


# How much a decibel of suppression is worth against a point of ergonomics. Loudness runs 0 to -39
# and is the whole reason a suppressor is fitted, but it was not in the objective at all - so among
# cans the score picked whichever was lightest on ergonomics, not whichever was quietest. The AS VAL
# integral at -39 Loudness for -5 ergonomics lost to cans that barely muffle anything.
QUIET_WEIGHT = 0.5


_reach = {}


_inflight = set()


def capacity(tpl):
    carts = db[tpl]["_props"].get("Cartridges") or []
    return carts[0].get("_max_count", 0) if carts else 0


def build_stats(items):
    """Ergonomics and recoil of the finished weapon. Mod Recoil values are percentages that apply
    to the weapon's own RecoilForceUp/Back, so they sum and then scale - they are not additive
    with ergonomics and cannot be compared part-by-part."""
    p = db[items[0]["_tpl"]]["_props"]
    ergo = p.get("Ergonomics", 0) or 0
    pct = 0.0
    acc = 0.0
    for n in items[1:]:
        mp = db[n["_tpl"]]["_props"]
        ergo += mp.get("Ergonomics", 0) or 0
        pct += mp.get("Recoil", 0) or 0
        acc += mp.get("Accuracy", 0) or 0
    mult = 1 + pct / 100.0
    return ergo, (p.get("RecoilForceUp", 0) or 0) * mult, (p.get("RecoilForceBack", 0) or 0) * mult, pct, acc


def build_loudness(items):
    """Total suppression, negative for quieter. Not part of build_stats because it is not a
    handling stat - it is the reason a suppressor is fitted at all, and the frontier was blind to
    it, so a quiet build could only ever lose."""
    return sum(db[i["_tpl"]]["_props"].get("Loudness", 0) or 0 for i in items[1:])


def objective(items, w):
    ergo, _up, _back, pct, _acc = build_stats(items)
    return w[0] * ergo + w[1] * (-pct)


def zoom_levels(tpl):
    """Distinct magnifications an optic offers. Two or more means it toggles - the Elcan Specter
    DR flips 1x/4x, the Vudu runs 1-6x. 26 of the 98 optics here are variable."""
    if tpl not in _zoom:
        z = (db.get(tpl, {}).get("_props") or {}).get("Zooms")
        flat = []
        if isinstance(z, list):
            for row in z:
                flat += row if isinstance(row, list) else [row]
        _zoom[tpl] = sorted({float(x) for x in flat if isinstance(x, (int, float))})
    return _zoom[tpl]


def optic_class(tpl):
    """Category is a far better guide to what an optic is for than its Zooms field, which reports
    the magnification value but does not reliably mark a scope as variable - the Nightforce NXS
    2.5-10x24 claims a flat 1x. Collimators are dots, AssaultScope is the 1-4x class, OpticScope
    is a full scope (15 of the 24 here are variable)."""
    c = categories(tpl)
    if "CompactCollimator" in c or "Collimator" in c:
        return "dot"
    if "AssaultScope" in c:
        return "low"
    if "OpticScope" in c:
        return "high"
    if "SpecialScope" in c:
        return "special"
    return None


def optic_rank(tpl, policy):
    """Lower is more wanted. Never excludes anything outright - a gun that can only take one kind
    of sight still gets one."""
    k = optic_class(tpl)
    variable = len(zoom_levels(tpl)) > 1
    if policy == "reddot":                      # pistol-calibre automatics: no magnification
        return {"dot": 0, "low": 2, "high": 3, "special": 4}.get(k, 5)
    if policy == "long":                        # full-power: reach, ideally toggling
        if k == "high":
            return 0 if variable else 1
        return {"low": 2, "dot": 3, "special": 4}.get(k, 5)
    if k == "low":                              # intermediate rifle: low-power, toggles 1x/4x
        return 0
    if k == "high":
        return 1 if variable else 2
    return {"dot": 3, "special": 4}.get(k, 5)


def optic_tiers(cands, policy):
    """Preference order, best first, falling through to whatever exists."""
    ranked = {}
    for c in cands:
        ranked.setdefault(optic_rank(c, policy), []).append(c)
    return [ranked[k] for k in sorted(ranked)]


def optic_reach(tpl, policy, _depth=0):
    """(best sight rank reachable from here, how many parts it takes). None if no sight at all.

    Both halves matter, and in that order. Judging only by distance made "shortest" beat "better
    sight": the VSK-94 took a red dot that bolted straight on, over the 1-4x scope two plates away,
    on a 9x39 marksman rifle. Judging only by rank is what built the four-plate tower in the first
    place. Rank decides, distance breaks the tie.

    Ignores what is already fitted so it can be cached - a route blocked by a conflict is filtered
    out by pick() before this matters.
    """
    if is_optic(tpl):
        return (optic_rank(tpl, policy), 0)
    if _depth >= LOOKAHEAD:
        return None
    key = (tpl, policy, _depth)
    if key in _reach:
        return _reach[key]
    if key in _inflight:
        # A cycle. Return unreachable for THIS branch without caching it - writing None into
        # the memo here poisoned every caller above, and rifles lost 58 magnified optics to it.
        return None
    _inflight.add(key)
    best = None
    for s in (db.get(tpl, {}).get("_props") or {}).get("Slots", []) or []:
        n = s.get("_name") or ""
        if not n.startswith(("mod_scope", "mod_sight", "mod_mount")):
            continue
        f = (s.get("_props") or {}).get("filters", [{}])[0]
        for c in (f.get("Filter") or []):
            r = optic_reach(c, policy, _depth + 1)
            if r is None:
                continue
            cand = (r[0], r[1] + 1)
            if best is None or cand < best:
                best = cand
    _inflight.discard(key)
    _reach[key] = best
    return best


def can_carry_optic(tpl, placed, policy):
    """Does this mount lead to a sight we actually want? A variable scope needs 30mm rings that
    score worse on ergonomics than a bare red dot, so without this the greedy takes the dot and
    the scope never gets a chance."""
    for s in (db.get(tpl, {}).get("_props") or {}).get("Slots", []) or []:
        n = s.get("_name") or ""
        if not (n.startswith("mod_scope") or n.startswith("mod_sight")):
            continue
        f = (s.get("_props") or {}).get("filters", [{}])[0]
        for c in (f.get("Filter") or []):
            if is_optic(c) and optic_rank(c, policy) <= 1 and compatible(c, placed | {tpl}):
                return True
    return False


def suppressor_friendly(tpl, placed):
    """Could this part still take a silencer once fitted? Used to steer barrel choice."""
    for s in (db.get(tpl, {}).get("_props") or {}).get("Slots", []) or []:
        if not (s.get("_name") or "").startswith("mod_muzzle"):
            continue
        f = (s.get("_props") or {}).get("filters", [{}])[0]
        for c in (f.get("Filter") or []):
            if is_suppressor(c) and compatible(c, placed | {tpl}):
                return True
    return False


def compatible(tpl, placed):
    if not OPT["conflicts"]:
        return True
    # The database records these one-directionally - the handguard names the barrel but not the
    # reverse - so both directions have to be checked or roughly half go unnoticed.
    if conflicts(tpl) & placed:
        return False
    return not any(tpl in conflicts(p) for p in placed)


def shape_ok(its, reference, w=(1.0, 1.0)):
    """Refinement optimises ergonomics and recoil, and every preference here costs one or both:
    a suppressor is heavy, a combo light adds nothing, a variable optic weighs more than a dot.
    Left alone it would trade all of them away for a couple of points. Hold the shape.

    Magazines are the worst case, because `objective` cannot see capacity at all. Left to itself
    refinement put a 40-round three-slot PMAG on the M4A1 when a 60-round two-slot MAG5 was
    available - worse on both counts, but better on ergonomics."""
    if sum(1 for i in its if is_optic(i["_tpl"])) > 1:
        return False

    def had(pred):
        return any(pred(i["_tpl"]) for i in reference)

    def has(pred):
        return any(pred(i["_tpl"]) for i in its)

    for pred in (is_light, is_combo, is_suppressor):
        if had(pred) and not has(pred):
            return False

    # Don't let a toggling optic be swapped for a fixed one.
    if had(lambda t: is_optic(t) and len(zoom_levels(t)) > 1) and \
       not has(lambda t: is_optic(t) and len(zoom_levels(t)) > 1):
        return False

    # Never grow the magazine's footprint, and on an automatic never shrink its capacity - those
    # are the two things the objective is blind to.
    if _mag_footprint(its) > _mag_footprint(reference):
        return False
    if is_auto() and _mag_capacity(its) < _mag_capacity(reference):
        return False
    return True


def weapon_weights(tpl):
    """How much ergonomics is worth against recoil, for this kind of gun.

    The original score was `Ergonomics - Recoil`, which weights the two equally on every weapon.
    That is wrong in opposite directions at the extremes: on a full-auto rifle it will take a
    +21 ergo stock over a -18 recoil one, and on a bolt-action it pays for recoil control that
    barely matters between shots. Read the fire modes rather than guessing from category names.
    """
    if weapon_is_auto(tpl):
        return (1.0, 2.0)      # holding the trigger down - recoil dominates
    return (1.8, 0.8)          # one shot at a time - handling matters more


def is_weapon(tpl):
    seen, cur = 0, db.get(tpl)
    while cur and seen < 12:
        if cur["_id"] == WEAPON_BASE:
            return True
        cur = db.get(cur.get("_parent")); seen += 1
    return False


def usable(tpl):
    it = db.get(tpl)
    if not it or not it.get("_props"):
        return False
    p = it["_props"]
    if p.get("QuestItem"):
        return False
    # A part has to be purchasable at the trader level a build describes; meta builds assume max
    # standing and full availability. Being sellable on the flea is a different question and only
    # matters if these builds are being used to exercise a flea-buying mod - it was on by default
    # and quietly excluded good kit, the SureFire MAG5-60 among it.
    if OPT["flea-only"] and p.get("CanSellOnRagfair") is False:
        return False
    return True


def _mag_capacity(its):
    return max((capacity(i["_tpl"]) for i in its if is_magazine(i["_tpl"])), default=0)


def score(tpl, slot="", w=(1.0, 1.0)):
    p = db[tpl]["_props"]
    we, wr = w
    if is_suppressor(tpl):
        # Loudness is stored negative, so negating it makes quiet a positive. Recoil and ergonomics
        # still count through the usual terms below - a can that also steadies the weapon is
        # already rewarded for it.
        return (we * (p.get("Ergonomics", 0) or 0) + wr * (-(p.get("Recoil", 0) or 0))
                + QUIET_WEIGHT * -(p.get("Loudness", 0) or 0))
    if slot == "mod_magazine":
        # Capacity is only worth chasing where the magazine actually empties. On a bolt-action or
        # a semi-auto the extra rounds buy little and cost ergonomics and length, so those score
        # on handling like any other part.
        if not OPT["mag-capacity"] or is_auto():
            return capacity(tpl)
    return we * (p.get("Ergonomics", 0) or 0) + wr * (-(p.get("Recoil", 0) or 0))


def narrow(cands, slot_name, placed, chain=()):
    """Two things the ergonomics/recoil score cannot express on its own.

    One optic per gun. The receiver, the handguard and a side mount each offer a scope slot, and
    scoring each in isolation cheerfully fits an optic in all three - 31% of builds carried more
    than one sight and a few carried four.

    And a light is worth having but scores zero on both ergonomics and recoil, so it loses every
    contest on merit and 37% of builds ended up with nothing to see in the dark with. Give the
    first tactical slot to a light, then let the score decide the rest.
    """
    # An underbarrel launcher is never worth what it costs. mod_launcher accepts nothing but
    # launchers, so leaving it empty loses nothing - and the GP-25 conflicts with 72 other parts,
    # which is how 43 builds ended up with no foregrip. A weapon that IS a launcher is untouched;
    # this only declines to hang one under another gun.
    if not OPT["launchers"] and (slot_name or "").startswith("mod_launcher"):
        return []
    if OPT["one-optic"] and any(is_optic(p) for p in placed):
        # Where the slot offers something else, take that. Where every candidate is an optic -
        # a dedicated scope mount - leave it empty. Falling back to "fit one anyway" is what kept
        # a second sight on 20% of builds after the first attempt at this.
        cands = [c for c in cands if not is_optic(c)]
        if not cands:
            return []
    if OPT["light"] and (slot_name or "").startswith("mod_tactical") \
            and not any(is_light(p) for p in placed):
        # Prefer a light/laser combo over a bare torch - that is the AN/PEQ family.
        combos = [c for c in cands if is_combo(c)]
        lights = combos or [c for c in cands if is_light(c)]
        if lights:
            cands = lights
    elif OPT["light"] and (slot_name or "").startswith("mod_tactical"):
        # Already lit. A second torch is -2 ergonomics and lights nothing new. Most tactical
        # slots offer nothing BUT lights, so "use a non-light if one exists" quietly changed
        # nothing and builds wore up to six - leave the slot empty instead.
        cands = [c for c in cands if not is_light(c)]
        if not cands:
            return []

    # Suppressed by preference. Where the muzzle slot takes a silencer directly, use one; where it
    # does not, the best-scoring device often *is* a thread adapter, and this same rule applies
    # again at its own muzzle slot on the way down.
    # Magazines are scored on capacity, which always reaches for the biggest one - and the biggest
    # is usually the one that eats a third rig slot. An extended magazine that still fits the usual
    # two is worth having; a drum is not. Where a gun has nothing smaller, take what there is
    # rather than leave it unfed.
    if OPT["compact-mags"] and (slot_name or "").startswith("mod_magazine"):
        compact = [c for c in cands if mag_slots(c) <= 2]
        if compact:
            cands = compact

    if OPT["suppressor"] and (slot_name or "").startswith("mod_muzzle"):
        sup = [c for c in cands if is_suppressor(c)]
        if sup:
            cands = sup

    # The barrel decides the muzzle before the muzzle slot is ever reached: a short barrel that
    # conflicts with every silencer quietly rules out suppressing the gun. Prefer barrels that
    # leave the option open.
    if OPT["suppressor"] and (slot_name or "").startswith("mod_barrel"):
        friendly = [c for c in cands if suppressor_friendly(c, placed)]
        if friendly:
            cands = friendly

    # Sight to suit the calibre: none on pistol-calibre automatics, something that toggles between
    # low and high on intermediate rifles, real magnification on full-power rounds.
    #
    # Drop the optics we do not want but KEEP everything else in the slot. Most scope slots offer
    # mounts alongside optics, and the mount is often how the optic attaches at all - filtering the
    # slot down to optics broke that path, so this only ever narrows which *optic* can win.
    # Stop the tower. Mount plates read positive on ergonomics, so each step was happy to add
    # one more; the optic block below never saw these slots because they offer no optic of their
    # own. Once MAX_MOUNTS plates are under the sight, only a sight itself may go on.
    # Deliberately NOT gated on short-mounts. That toggle also rewrites optic selection, which is
    # what cost 58 magnified optics, and every use of MAX_MOUNTS used to sit behind it - so with
    # the toggle off (the default) the cap was dead code and changing it did nothing at all.
    # Capping the stack and choosing the optic are separate concerns; only the first belongs here.
    if (slot_name or "").startswith(("mod_scope", "mod_sight", "mod_mount")):
        if sum(1 for t in chain if is_mounting_part(t)) >= MAX_MOUNTS:
            sights = [c for c in cands if is_optic(c)]
            if not sights:
                return []
            cands = sights

    optics = [c for c in cands if is_optic(c)] if OPT["optic-policy"] else []
    if optics:
        for tier in optic_tiers(optics, POLICY):
            if tier:
                keep = set(tier)
                if not OPT["short-mounts"]:
                    cands = [c for c in cands
                             if (is_optic(c) and c in keep)
                             or (not is_optic(c) and can_carry_optic(c, placed, POLICY))]
                    if not cands:
                        cands = tier
                    break

                # Weigh what a route reaches against what it costs to get there. Every candidate
                # is scored (best sight rank reachable, parts needed) and only the best survive -
                # so a scope two plates away beats a red dot that bolts straight on, and a dot
                # that bolts straight on beats the same dot up a tower of adapters.
                # Count what is already holding this sight up. optic_reach only says how far a
                # route *could* reach; it cannot see the plates already fitted, so without this
                # every step happily added one more and the tower came back.
                fitted = sum(1 for t in chain if is_mounting_part(t))
                scored = []
                for c in cands:
                    if is_optic(c):
                        r = (optic_rank(c, POLICY), 0)
                    elif fitted >= MAX_MOUNTS:
                        r = None        # enough plates already
                    else:
                        r = optic_reach(c, POLICY)
                    if r is not None:
                        scored.append((r, c))
                if scored:
                    best = min(r for r, _ in scored)
                    cands = [c for r, c in scored if r == best]
                else:
                    cands = tier
                break
    return cands

