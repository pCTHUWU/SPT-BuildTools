"""Generate meta weapon builds for the SPT profile.

Each slot's part is chosen by maximising (Ergonomics - Recoil) among the parts that slot's own
filter allows, so every build is valid by construction rather than by guesswork. Magazines are
scored on capacity instead, since ergonomics alone picks a 10-round PMAG.

Preview by default; pass --write to save into the profile.
"""
import json, random, sys
from options import OPT, ITEMS, LOCALE, resolve_profile

DB   = ITEMS
LOC  = LOCALE
PROF = resolve_profile()

WEAPON_BASE = "5422acb9af1c889c16000029"   # Weapon
TAG = "(meta)"                              # marks builds this script owns

db  = json.load(open(DB,  encoding="utf-8"))
loc = json.load(open(LOC, encoding="utf-8"))

def name(tpl):
    return loc.get(f"{tpl} Name") or db.get(tpl, {}).get("_name", tpl)

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

def short_name(tpl):
    return loc.get(f"{tpl} ShortName") or name(tpl)

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

def new_id(_used=set()):
    while True:
        i = "".join(random.choice("0123456789abcdef") for _ in range(24))
        if i not in _used:
            _used.add(i); return i

def capacity(tpl):
    carts = db[tpl]["_props"].get("Cartridges") or []
    return carts[0].get("_max_count", 0) if carts else 0

def weapon_weights(tpl):
    """How much ergonomics is worth against recoil, for this kind of gun.

    The original score was `Ergonomics - Recoil`, which weights the two equally on every weapon.
    That is wrong in opposite directions at the extremes: on a full-auto rifle it will take a
    +21 ergo stock over a -18 recoil one, and on a bolt-action it pays for recoil control that
    barely matters between shots. Read the fire modes rather than guessing from category names.
    """
    fire = set((db[tpl]["_props"].get("weapFireType") or []))
    if fire & {"fullauto", "burst"}:
        return (1.0, 2.0)      # holding the trigger down - recoil dominates
    return (1.8, 0.8)          # one shot at a time - handling matters more

def is_auto(w):
    """weapon_weights gives (1.0, 2.0) to full-auto and (1.8, 0.8) to everything else."""
    return w[1] > w[0]

def score(tpl, slot="", w=(1.0, 1.0)):
    p = db[tpl]["_props"]
    we, wr = w
    if slot == "mod_magazine":
        # Capacity is only worth chasing where the magazine actually empties. On a bolt-action or
        # a semi-auto the extra rounds buy little and cost ergonomics and length, so those score
        # on handling like any other part.
        if not OPT["mag-capacity"] or is_auto(w):
            return capacity(tpl)
    return we * (p.get("Ergonomics", 0) or 0) + wr * (-(p.get("Recoil", 0) or 0))

def build_stats(items):
    """Ergonomics and recoil of the finished weapon. Mod Recoil values are percentages that apply
    to the weapon's own RecoilForceUp/Back, so they sum and then scale - they are not additive
    with ergonomics and cannot be compared part-by-part."""
    p = db[items[0]["_tpl"]]["_props"]
    ergo = p.get("Ergonomics", 0) or 0
    pct = 0.0
    for n in items[1:]:
        mp = db[n["_tpl"]]["_props"]
        ergo += mp.get("Ergonomics", 0) or 0
        pct += mp.get("Recoil", 0) or 0
    mult = 1 + pct / 100.0
    return ergo, (p.get("RecoilForceUp", 0) or 0) * mult, (p.get("RecoilForceBack", 0) or 0) * mult, pct

def objective(items, w):
    ergo, _up, _back, pct = build_stats(items)
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
_conf = {}
def conflicts(tpl):
    if tpl not in _conf:
        it = db.get(tpl) or {}
        _conf[tpl] = frozenset((it.get("_props") or {}).get("ConflictingItems") or [])
    return _conf[tpl]

def compatible(tpl, placed):
    if not OPT["conflicts"]:
        return True
    # The database records these one-directionally - the handguard names the barrel but not the
    # reverse - so both directions have to be checked or roughly half go unnoticed.
    if conflicts(tpl) & placed:
        return False
    return not any(tpl in conflicts(p) for p in placed)

FORCED = []          # required slots that could only be filled with a conflicting part

_cat = {}
def categories(tpl):
    if tpl not in _cat:
        out, cur, n = [], db.get(tpl), 0
        while cur and n < 14:
            out.append(cur.get("_name") or "")
            cur = db.get(cur.get("_parent")); n += 1
        _cat[tpl] = out
    return _cat[tpl]

OPTIC_CATS = ("Collimator", "CompactCollimator", "OpticScope", "AssaultScope", "SpecialScope")
# CombTactical and LaserDesignator are empty categories in this database - the light/laser combos
# (AN/PEQ-15 and friends) are all TacticalCombo, and there are only 3 plain Flashlights.
LIGHT_CATS = ("Flashlight", "TacticalCombo")

def is_optic(tpl):
    return any(c in categories(tpl) for c in OPTIC_CATS)

def is_light(tpl):
    return any(c in categories(tpl) for c in LIGHT_CATS)

def is_combo(tpl):
    return "TacticalCombo" in categories(tpl)

def is_suppressor(tpl):
    return "Silencer" in categories(tpl)

def mag_slots(tpl):
    """Grid footprint. A standard rifle magazine is 1x2; drums and long extendeds are 1x3 or 2x2."""
    p = db.get(tpl, {}).get("_props") or {}
    return (p.get("Width") or 0) * (p.get("Height") or 0)

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
SHORT_CAL = {"Caliber9x19PARA", "Caliber9x18PM", "Caliber9x21", "Caliber1143x23ACP",
             "Caliber762x25TT", "Caliber57x28", "Caliber46x30", "Caliber12g", "Caliber20g",
             "Caliber23x75", "Caliber366TKM", "Caliber127x33"}
# Full-power and magnum: reach for real magnification.
LONG_CAL = {"Caliber762x51", "Caliber762x54R", "Caliber86x70", "Caliber127x55", "Caliber9x39"}

POLICY = "lpvo"      # set per build in make(); these scripts build one gun at a time

def optic_policy(weapon_tpl):
    cal = (db[weapon_tpl]["_props"].get("ammoCaliber") or "")
    if cal in SHORT_CAL:
        return "reddot"
    if cal in LONG_CAL:
        return "long"
    return "lpvo"

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

def narrow(cands, slot_name, placed):
    """Two things the ergonomics/recoil score cannot express on its own.

    One optic per gun. The receiver, the handguard and a side mount each offer a scope slot, and
    scoring each in isolation cheerfully fits an optic in all three - 31% of builds carried more
    than one sight and a few carried four.

    And a light is worth having but scores zero on both ergonomics and recoil, so it loses every
    contest on merit and 37% of builds ended up with nothing to see in the dark with. Give the
    first tactical slot to a light, then let the score decide the rest.
    """
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
    optics = [c for c in cands if is_optic(c)] if OPT["optic-policy"] else []
    if optics:
        for tier in optic_tiers(optics, POLICY):
            if tier:
                keep = set(tier)
                # Keep the wanted optics, and keep any mount that can carry one. Dropping mounts
                # outright breaks the only path to a scope on some guns; keeping every mount lets
                # the ergonomics score pick a bare rail over the sight we asked for.
                cands = [c for c in cands
                         if (is_optic(c) and c in keep)
                         or (not is_optic(c) and can_carry_optic(c, placed, POLICY))]
                if not cands:
                    cands = tier
                break
    return cands

def is_magazine(tpl):
    return "Magazine" in categories(tpl)

def _mag_footprint(its):
    return max((mag_slots(i["_tpl"]) for i in its if is_magazine(i["_tpl"])), default=0)

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
    if is_auto(w) and _mag_capacity(its) < _mag_capacity(reference):
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
_SLOT_RANK = {"mod_pistol_grip": 9}
def slot_rank(n):
    if (n or "").startswith("mod_stock"):
        return 0
    return _SLOT_RANK.get(n, 5)

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
        cands = narrow(cands, s["_name"], placed)
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

def make(weapon_tpl):
    global POLICY
    POLICY = optic_policy(weapon_tpl)
    w = weapon_weights(weapon_tpl)
    items, placed = [], set()
    grow(weapon_tpl, None, None, 0, (), placed, w, items)
    return refine(items, w), w

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
    ergo, up, back, pct = build_stats(items)
    STATS.append((short, ergo, up, pct))
    kind = "auto" if w[1] > w[0] else "semi"
    print(f"  {short:<12} {len(items):>3} parts  {kind}  ergo {ergo:>4.0f}  "
          f"recoil {up:>5.0f}/{back:>5.0f} ({pct:+.0f}%)   {want}")

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
