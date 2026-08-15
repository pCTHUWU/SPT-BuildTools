"""Generate meta weapon builds for the SPT profile.

Each slot's part is chosen by maximising (Ergonomics - Recoil) among the parts that slot's own
filter allows, so every build is valid by construction rather than by guesswork. Magazines are
scored on capacity instead, since ergonomics alone picks a 10-round PMAG.

Preview by default; pass --write to save into the profile.
"""
import json, random, sys
from options import OPT, ITEMS, LOCALE, resolve_profile
from buildlib import (OPTIC_CATS, LIGHT_CATS, SHORT_CAL, LONG_CAL, LOOKAHEAD, NOT_MOUNTING, 
    _SLOT_RANK, EARNS_PLACE, _conf, _cat, new_id, name, categories, conflicts, slot_rank, 
    slot_required, is_optic, is_light, is_combo, is_magazine, is_suppressor, is_mounting_part, 
    is_stock_slot, mag_slots, _mag_footprint, optic_policy, earns_place, prune_empty, 
    short_name, weapon_is_auto, dominates, pareto_front, _knee, db, loc)

DB   = ITEMS
LOC  = LOCALE
PROF = resolve_profile()

WEAPON_BASE = "5422acb9af1c889c16000029"   # Weapon
TAG = "(meta)"                              # marks builds this script owns


def is_weapon(tpl):
    seen, cur = 0, db.get(tpl)
    while cur and seen < 12:
        if cur["_id"] == WEAPON_BASE:
            return True
        cur = db.get(cur.get("_parent")); seen += 1
    return False

# Pick weapons by name so a wrong hardcoded id can't slip through.
WANTED = [
    ("Colt M4A1 5.56x45 assault rifle",                        "M4A1"),
    ("HK 416A5 5.56x45 assault rifle",                         "HK 416A5"),
    ("Kalashnikov AK-74N 5.45x39 assault rifle",               "AK-74N"),
    ("Kalashnikov AKM 7.62x39 assault rifle",                  "AKM"),
    ("SIG MCX-SPEAR 6.8x51 assault rifle",                     "MCX-SPEAR"),
    ("HK G36 5.56x45 assault rifle",                           "G36"),
    ("SIG MPX 9x19 submachine gun",                            "MPX"),
    ("HK MP7A2 4.6x30 submachine gun",                         "MP7A2"),
    ("TDI KRISS Vector Gen.2 9x19 submachine gun",             "Vector 9x19"),
    ("Knight's Armament Company SR-25 7.62x51 marksman rifle", "SR-25"),
    ("Remington R11 RSASS 7.62x51 marksman rifle",             "RSASS"),
    ("Accuracy International AXMC .338 LM bolt-action sniper rifle", "AXMC"),
    ("Remington Model 700 7.62x51 bolt-action sniper rifle",   "M700"),
    ("Mossberg 590A1 12ga pump-action shotgun",                "590A1"),
    ("Degtyarev RPD 7.62x39 machine gun",                      "RPD"),
]


by_name = {}
for tpl, it in db.items():
    if it.get("_type") == "Item" and is_weapon(tpl):
        by_name.setdefault(name(tpl), tpl)

# --all: every weapon in the game, not just the curated list.
if "--all" in sys.argv:
    seen = {}
    WANTED = []
    for full, tpl in sorted(by_name.items()):
        if not db[tpl]["_props"].get("Slots"):
            continue                      # nothing to build - a bare frame
        s = short_name(tpl)
        seen[s] = seen.get(s, 0) + 1
        WANTED.append((full, s if seen[s] == 1 else f"{s} #{seen[s]}"))


def capacity(tpl):
    carts = db[tpl]["_props"].get("Cartridges") or []
    return carts[0].get("_max_count", 0) if carts else 0

AUTO = False   # set per build in make(); the weapon's own fire modes, never the weighting


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

def is_auto():
    """Whether the weapon being built is automatic.

    This used to infer it from the weighting - `w[1] > w[0]` - which held only while
    weapon_weights was the sole producer of those tuples. The Pareto sweep broke that invariant:
    it feeds (1.4, 1.4) and (1.8, 0.8) to genuine automatics, both of which read as semi-auto,
    so two candidates in every three silently lost their magazine capacity rule and reached for
    a 10-round PMAG. Read the weapon, not the weights.
    """
    return AUTO

# How much a decibel of suppression is worth against a point of ergonomics. Loudness runs 0 to -39
# and is the whole reason a suppressor is fitted, but it was not in the objective at all - so among
# cans the score picked whichever was lightest on ergonomics, not whichever was quietest. The AS VAL
# integral at -39 Loudness for -5 ergonomics lost to cans that barely muffle anything.
QUIET_WEIGHT = 0.5

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

SKIP = {"mod_charge_001"}                    # redundant duplicate slots

# A slot's own filter is not the whole compatibility story. ConflictingItems is a *cross-slot*
# rule - a railed dust cover rejecting the standard rear sight, a grip with a built-in stock
# rejecting a separate stock, a handguard longer than the barrel under it. Choosing the best part
# per slot independently, as this script first did, produced 442 such violations across 248 of
# 760 builds: every part legal for its own slot, a third of the builds refusing to assemble.

def compatible(tpl, placed):
    if not OPT["conflicts"]:
        return True
    # The database records these one-directionally - the handguard names the barrel but not the
    # reverse - so both directions have to be checked or roughly half go unnoticed.
    if conflicts(tpl) & placed:
        return False
    return not any(tpl in conflicts(p) for p in placed)

FORCED = []          # required slots that could only be filled with a conflicting part


_zoom = {}
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

# Short range: pistol-calibre and shot. No magnification wanted - a zoom optic on an automatic
# SMG is in the way.
# Full-power and magnum: reach for real magnification.

POLICY = "lpvo"      # set per build in make(); these scripts build one gun at a time


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

# How many mounting parts a sight is worth. Two adapters to reach a scope is a mount;
# four is a tower, and the ergonomics score rewards building one because plates read
# positive. Past this the best sight reachable within the cap wins instead.
MAX_MOUNTS = 2      # plates allowed between gun and sight; enforced always, not just short-mounts


_reach = {}
_inflight = set()
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


def _mag_capacity(its):
    return max((capacity(i["_tpl"]) for i in its if is_magazine(i["_tpl"])), default=0)

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

# Sibling slots are filled depth-first in the order the database lists them, and with conflict
# checking that order decides who wins a contested pair. It has to be chosen, not inherited.
#
# The shoulder stock goes first. Several "pistol grips" - the Hera Arms CQR family - are really
# grips with an integrated stock, and they conflict with every real stock. Filling the grip first
# left the rifle with a bare buffer tube and no stock at all: legal, and useless. Filling the stock
# chain first puts a real stock on and pushes the grip to an ordinary compatible one, which is what
# a recoil-focused build wants anyway.


def pick(allowed, chain, placed, required):
    base = [c for c in allowed if usable(c) and c not in chain]
    if not base and required:
        # A required slot must be filled for the build to be valid, even if the only candidates
        # cannot be bought off the flea (the AK-50's barrel, for one).
        base = [c for c in allowed if db.get(c) and db[c].get("_props") and c not in chain]
    ok = [c for c in base if compatible(c, placed)]
    if ok:
        return ok, False
    if base and required:
        return base, True      # boxed in by an earlier pick; an empty required slot is worse
    return [], False

RECORDING = True     # suppress FORCED logging while refinement is trying things out

def grow(tpl, parent_id, slot_name, depth, chain, placed, w, out):
    """Fill tpl's slots depth-first, appending nodes to `out`."""
    node = {"_id": new_id(), "_tpl": tpl}
    if parent_id:
        node["parentId"] = parent_id
        node["slotId"] = slot_name
    out.append(node)
    placed.add(tpl)
    if depth >= 6:
        return
    for s in sorted(db[tpl]["_props"].get("Slots", []),
                    key=lambda x: slot_rank(x.get("_name"))):
        if s["_name"] in SKIP:
            continue
        allowed = s["_props"]["filters"][0]["Filter"]
        # A stock is must-fill even where the database marks it optional - a rifle without one
        # is not a build worth saving.
        cands, forced = pick(allowed, chain, placed, s["_required"] or (OPT["stock"] and is_stock_slot(s)))
        if not cands:
            continue
        if forced and RECORDING:
            FORCED.append(f"{name(tpl)}.{s['_name']}")
        cands = narrow(cands, s["_name"], placed, chain + (tpl,))
        if not cands:
            continue          # narrow() can empty a slot on purpose - a second optic mount
        best = max(cands, key=lambda c: score(c, s["_name"], w))
        grow(best, node["_id"], s["_name"], depth + 1, chain + (tpl,), placed, w, out)

def _swap(items, node, alt, w):
    """Replace one part and everything hanging off it. Returns the new item list, or None if the
    replacement is not compatible with what is already on the gun."""
    drop, changed = {node["_id"]}, True
    while changed:                       # node's whole subtree goes with it
        changed = False
        for i in items:
            if i.get("parentId") in drop and i["_id"] not in drop:
                drop.add(i["_id"]); changed = True
    keep = [i for i in items if i["_id"] not in drop]
    placed = {i["_tpl"] for i in keep}
    if not compatible(alt, placed):
        return None
    chain, cur = [], next((x for x in keep if x["_id"] == node.get("parentId")), None)
    while cur:
        chain.append(cur["_tpl"])
        cur = next((x for x in keep if x["_id"] == cur.get("parentId")), None)
    sub = []
    grow(alt, node["parentId"], node["slotId"], len(chain), tuple(chain), placed, w, sub)
    return keep + sub

def refine(items, w, rounds=3, breadth=6):
    """Greedy fills each slot knowing nothing about what comes after it, so a part chosen early
    can be a poor fit for the finished gun. Sweep the built weapon and try swapping each part for
    its alternatives, keeping any change that improves the weapon as a whole."""
    if not OPT["refine"]:
        return items
    global RECORDING
    was, RECORDING = RECORDING, False
    best = items
    try:
        for _ in range(rounds):
            improved = False
            for idx in range(1, len(best)):
                node = best[idx]
                parent = next((x for x in best if x["_id"] == node.get("parentId")), None)
                if parent is None:
                    continue
                slot = next((s for s in db[parent["_tpl"]]["_props"].get("Slots", []) or []
                             if s["_name"] == node.get("slotId")), None)
                if not slot:
                    continue
                alts = [c for c in slot["_props"]["filters"][0]["Filter"]
                        if c != node["_tpl"] and usable(c)]
                alts.sort(key=lambda c: score(c, node["slotId"], w), reverse=True)
                for alt in alts[:breadth]:
                    cand = _swap(best, node, alt, w)
                    if cand and shape_ok(cand, best, w) and objective(cand, w) > objective(best, w) + 1e-9:
                        best, improved = cand, True
                        break
                if improved:
                    break                # list indices shifted; restart the sweep
            if not improved:
                break
    finally:
        RECORDING = was
    return best

# Categories that do a job the ergonomics/recoil numbers cannot express, so they earn their place
# even at a cost. Bipods are handled separately - see earns_place.


# One fixed weighting bakes the same ergonomics-versus-recoil trade into every gun, and it is the
# wrong trade at both ends. Build several and keep the ones nothing else beats outright.
WEIGHT_SWEEP = [(1.0, 2.0), (1.4, 1.4), (1.8, 0.8)]


def make(weapon_tpl):
    global POLICY, AUTO
    POLICY = optic_policy(weapon_tpl)
    AUTO = weapon_is_auto(weapon_tpl)

    if not OPT["pareto"]:
        w = weapon_weights(weapon_tpl)
        items, placed = [], set()
        grow(weapon_tpl, None, None, 0, (), placed, w, items)
        return prune_empty(refine(items, w)), w

    wanted_suppressed = OPT["suppressor"]
    variants = []
    for suppressed in ([True, False] if wanted_suppressed else [False]):
        OPT["suppressor"] = suppressed          # single-threaded; restored below
        for w in WEIGHT_SWEEP:
            items, placed = [], set()
            grow(weapon_tpl, None, None, 0, (), placed, w, items)
            items = prune_empty(refine(items, w))
            ergo, up, _back, _pct, acc = build_stats(items)
            variants.append(((ergo, acc, -up, -build_loudness(items)), (items, w, suppressed)))
    OPT["suppressor"] = wanted_suppressed

    front = pareto_front(variants) or variants

    # Suppressed by preference, decided by the frontier rather than a fixed ergonomics budget.
    #
    # The old rule compared best-quiet against best-loud on *ergonomics alone* and went loud if the
    # gap beat SUPPRESSOR_ERGO_BUDGET = 12. That judged a three-way trade on one axis: a suppressor
    # also cuts recoil (every one in this database does, -7 to -15) and cuts noise, which is the
    # entire reason to fit one. At a budget of 12 the M4A1's -28 can and the SVD's -22 both lost,
    # i.e. "prefer suppressed" almost never held.
    #
    # The frontier already answers this properly: it has removed everything beaten outright on
    # ergonomics, accuracy *and* recoil together. So a suppressed build that survives is not
    # dominated, and the stated preference stands. If every quiet candidate is dominated, none
    # survive and the loud build wins on merit rather than on a threshold.
    pool = front
    if wanted_suppressed:
        quiet = [p for p in front if p[1][2]]
        if quiet:
            pool = quiet

    chosen = _knee(pool)
    return chosen[1][0], chosen[1][1]

builds = []
missing = []
STATS = []
for want, short in WANTED:
    tpl = by_name.get(want)
    if not tpl:
        missing.append(want); continue
    items, w = make(tpl)
    builds.append({
        "Id": new_id(),
        "Name": f"{short} {TAG}",
        "Root": items[0]["_id"],
        "Items": items,
    })
    ergo, up, back, pct, acc = build_stats(items)
    STATS.append((short, ergo, up, pct))
    kind = "auto" if weapon_is_auto(tpl) else "semi"
    print(f"  {short:<12} {len(items):>3} parts  {kind}  ergo {ergo:>4.0f}  "
          f"recoil {up:>5.0f}/{back:>5.0f} ({pct:+.0f}%)  acc {acc:+4.0f}   {want}")

if missing:
    print("\nNOT FOUND (name mismatch):")
    for m in missing:
        print("  " + m)

print(f"\n{len(builds)} build(s), {sum(len(b['Items']) for b in builds)} parts total")
if FORCED:
    print(f"\n{len(FORCED)} required slot(s) could only be filled with a conflicting part:")
    for f in sorted(set(FORCED)):
        print(f"    {f}")

if "--write" in sys.argv:
    prof = json.load(open(PROF, encoding="utf-8"))
    kept = [b for b in prof["userbuilds"]["weaponBuilds"] if TAG not in (b.get("Name") or "")]
    prof["userbuilds"]["weaponBuilds"] = kept + builds
    with open(PROF, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Written. kept {len(kept)} existing, added {len(builds)}.")
else:
    print("(preview only - pass --write to save)")
