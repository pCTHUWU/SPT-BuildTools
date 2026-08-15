"""Build one variant per trader loyalty level, to exercise the trader/flea fallback.

For level N, every slot is filled with the best part any trader sells at loyalty N or below.
Required slots no trader covers at that level fall back to the best part overall, which is
flea-only by definition - that is the case worth testing.

Default: M4A1 only.  --all: every weapon in the game.  --write saves.
Only ever touches builds tagged '(LL)'.
"""
import json, os, random, sys, collections
from options import OPT, DB_DIR, resolve_profile

ROOT = DB_DIR
PROF = resolve_profile()
M4A1 = "5447a9cd4bdc2dbd208b4567"
TAG  = "(LL)"
WEAPON_BASE = "5422acb9af1c889c16000029"

db  = json.load(open(f"{ROOT}/templates/items.json", encoding="utf-8"))
loc = json.load(open(f"{ROOT}/locales/global/en.json", encoding="utf-8"))

loyalty = {}
by_trader = collections.defaultdict(dict)
for t in os.listdir(f"{ROOT}/traders"):
    p = f"{ROOT}/traders/{t}/assort.json"
    if not os.path.exists(p):
        continue
    a = json.load(open(p, encoding="utf-8"))
    ll = a["loyal_level_items"]
    for it in a["items"]:
        if it.get("parentId") != "hideout":
            continue
        lvl = ll.get(it["_id"])
        if lvl is None:
            continue
        tpl = it["_tpl"]
        if tpl not in loyalty or lvl < loyalty[tpl]:
            loyalty[tpl] = lvl
        cur = by_trader[tpl].get(t)
        if cur is None or lvl < cur:
            by_trader[tpl][t] = lvl

_prof = json.load(open(PROF, encoding="utf-8"))
STANDING = {tid: (i.get("loyaltyLevel") or 0)
            for tid, i in _prof["characters"]["pmc"]["TradersInfo"].items()
            if i.get("unlocked")}

def buyable_now(tpl):
    return any(STANDING.get(t, 0) >= lvl for t, lvl in by_trader.get(tpl, {}).items())

def name(tpl):
    return loc.get(f"{tpl} Name") or db.get(tpl, {}).get("_name", tpl)

def short_name(tpl):
    return loc.get(f"{tpl} ShortName") or name(tpl)

def is_weapon(tpl):
    cur, seen = db.get(tpl), 0
    while cur and seen < 12:
        if cur["_id"] == WEAPON_BASE:
            return True
        cur = db.get(cur.get("_parent")); seen += 1
    return False

def new_id(_used=set()):
    while True:
        i = "".join(random.choice("0123456789abcdef") for _ in range(24))
        if i not in _used:
            _used.add(i); return i

def capacity(tpl):
    c = db[tpl]["_props"].get("Cartridges") or []
    return c[0].get("_max_count", 0) if c else 0

def weapon_weights(tpl):
    """See make_builds.py. Ergonomics and recoil are not worth the same on every gun; read the
    fire modes rather than weighting them equally as `Ergonomics - Recoil` did."""
    fire = set((db[tpl]["_props"].get("weapFireType") or []))
    if fire & {"fullauto", "burst"}:
        return (1.0, 2.0)
    return (1.8, 0.8)

def is_auto(w):
    """weapon_weights gives (1.0, 2.0) to full-auto and (1.8, 0.8) to everything else."""
    return w[1] > w[0]

def score(tpl, slot="", w=(1.0, 1.0)):
    p = db[tpl]["_props"]
    we, wr = w
    if slot == "mod_magazine":
        # Capacity is only worth chasing where the magazine actually empties - see make_builds.py.
        if not OPT["mag-capacity"] or is_auto(w):
            return capacity(tpl)
    return we * (p.get("Ergonomics", 0) or 0) + wr * (-(p.get("Recoil", 0) or 0))

def build_stats(items):
    """Mod Recoil values are percentages applied to the weapon's own RecoilForceUp/Back - they sum
    and then scale, so they cannot be compared part-by-part against ergonomics."""
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
    ergo, _u, _b, pct = build_stats(items)
    return w[0] * ergo + w[1] * (-pct)

def usable(tpl):
    it = db.get(tpl)
    if not it or not it.get("_props") or it["_props"].get("QuestItem"):
        return False
    # See make_builds.py. Trader level is the availability that matters here; the flea rule is
    # only for exercising a flea-buying mod, and it excluded good kit by default.
    if OPT["flea-only"] and it["_props"].get("CanSellOnRagfair") is False:
        return False
    return True

SKIP = {"mod_charge_001"}

# See make_builds.py for the full reasoning. Short version: a slot's own filter says nothing about
# ConflictingItems, which is a cross-slot rule (railed dust cover vs standard rear sight, grip with
# integrated stock vs separate stock, handguard longer than its barrel). Picking the best part per
# slot independently broke 248 of 760 builds.
_conf = {}
def conflicts(tpl):
    if tpl not in _conf:
        it = db.get(tpl) or {}
        _conf[tpl] = frozenset((it.get("_props") or {}).get("ConflictingItems") or [])
    return _conf[tpl]

def compatible(tpl, placed):
    if not OPT["conflicts"]:
        return True
    # Recorded one-directionally in the database, so check both ways.
    if conflicts(tpl) & placed:
        return False
    return not any(tpl in conflicts(p) for p in placed)

FORCED = []

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
# CombTactical and LaserDesignator are empty in this database; the light/laser combos are all
# TacticalCombo. See make_builds.py.
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
    if tpl not in _zoom:
        z = (db.get(tpl, {}).get("_props") or {}).get("Zooms")
        flat = []
        if isinstance(z, list):
            for row in z:
                flat += row if isinstance(row, list) else [row]
        _zoom[tpl] = sorted({float(x) for x in flat if isinstance(x, (int, float))})
    return _zoom[tpl]

SHORT_CAL = {"Caliber9x19PARA", "Caliber9x18PM", "Caliber9x21", "Caliber1143x23ACP",
             "Caliber762x25TT", "Caliber57x28", "Caliber46x30", "Caliber12g", "Caliber20g",
             "Caliber23x75", "Caliber366TKM", "Caliber127x33"}
LONG_CAL = {"Caliber762x51", "Caliber762x54R", "Caliber86x70", "Caliber127x55", "Caliber9x39"}

POLICY = "lpvo"

def optic_policy(weapon_tpl):
    cal = (db[weapon_tpl]["_props"].get("ammoCaliber") or "")
    if cal in SHORT_CAL:
        return "reddot"
    if cal in LONG_CAL:
        return "long"
    return "lpvo"

def optic_class(tpl):
    """Category beats the Zooms field, which gives magnification but does not reliably mark a
    scope as variable - the Nightforce NXS 2.5-10x24 claims a flat 1x. See make_builds.py."""
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
    k = optic_class(tpl)
    variable = len(zoom_levels(tpl)) > 1
    if policy == "reddot":
        return {"dot": 0, "low": 2, "high": 3, "special": 4}.get(k, 5)
    if policy == "long":
        if k == "high":
            return 0 if variable else 1
        return {"low": 2, "dot": 3, "special": 4}.get(k, 5)
    if k == "low":
        return 0
    if k == "high":
        return 1 if variable else 2
    return {"dot": 3, "special": 4}.get(k, 5)

def optic_tiers(cands, policy):
    ranked = {}
    for c in cands:
        ranked.setdefault(optic_rank(c, policy), []).append(c)
    return [ranked[k] for k in sorted(ranked)]

def can_carry_optic(tpl, placed, policy):
    """A variable scope needs rings that score worse on ergonomics than a bare red dot, so without
    this the greedy takes the dot and the scope never gets a chance."""
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
    """See make_builds.py. One optic per gun - receiver, handguard and side mount each offer a
    scope slot and scoring them in isolation fits an optic in all three. And a light scores zero
    on ergonomics and recoil so it loses every contest on merit; give it the first tactical slot."""
    # An underbarrel launcher is never worth what it costs. mod_launcher accepts nothing but
    # launchers, so leaving it empty loses nothing - and the GP-25 conflicts with 72 other parts,
    # which is how 43 builds ended up with no foregrip. A weapon that IS a launcher is untouched;
    # this only declines to hang one under another gun.
    if not OPT["launchers"] and (slot_name or "").startswith("mod_launcher"):
        return []
    if OPT["one-optic"] and any(is_optic(p) for p in placed):
        # Where every candidate is an optic - a dedicated scope mount - leave the slot empty
        # rather than fitting a second sight.
        cands = [c for c in cands if not is_optic(c)]
        if not cands:
            return []
    if OPT["light"] and (slot_name or "").startswith("mod_tactical") and not any(is_light(p) for p in placed):
        combos = [c for c in cands if is_combo(c)]
        lights = combos or [c for c in cands if is_light(c)]
        if lights:
            cands = lights

    # See make_builds.py. Capacity scoring always reaches for the biggest magazine, which is
    # usually the one that eats a third rig slot. Give way where a gun has nothing smaller.
    if OPT["compact-mags"] and (slot_name or "").startswith("mod_magazine"):
        compact = [c for c in cands if mag_slots(c) <= 2]
        if compact:
            cands = compact

    if OPT["suppressor"] and (slot_name or "").startswith("mod_muzzle"):
        sup = [c for c in cands if is_suppressor(c)]
        if sup:
            cands = sup

    # A short barrel that conflicts with every silencer rules out suppressing the gun before the
    # muzzle slot is reached. Prefer barrels that leave the option open.
    if OPT["suppressor"] and (slot_name or "").startswith("mod_barrel"):
        friendly = [c for c in cands if suppressor_friendly(c, placed)]
        if friendly:
            cands = friendly

    # Drop unwanted optics but keep everything else - a mount is often how the optic attaches.
    optics = [c for c in cands if is_optic(c)] if OPT["optic-policy"] else []
    if optics:
        for tier in optic_tiers(optics, POLICY):
            if tier:
                keep = set(tier)
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
    """Every preference costs ergonomics or recoil, so refinement would trade them all away."""
    if sum(1 for i in its if is_optic(i["_tpl"])) > 1:
        return False
    for pred in (is_light, is_combo, is_suppressor):
        if any(pred(i["_tpl"]) for i in reference) and not any(pred(i["_tpl"]) for i in its):
            return False
    if any(is_optic(i["_tpl"]) and len(zoom_levels(i["_tpl"])) > 1 for i in reference) and \
       not any(is_optic(i["_tpl"]) and len(zoom_levels(i["_tpl"])) > 1 for i in its):
        return False
    # Never grow the magazine footprint, and on an automatic never shrink its capacity - the
    # objective is blind to both.
    if _mag_footprint(its) > _mag_footprint(reference):
        return False
    if is_auto(w) and _mag_capacity(its) < _mag_capacity(reference):
        return False
    return True

# See make_builds.py. With conflict checking, sibling slot order decides who wins a contested
# pair, so it has to be chosen. Stock chain first: the Hera Arms CQR family are grips with an
# integrated stock that conflict with every real stock, and filling the grip first left rifles
# with a bare buffer tube and nothing on it.
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

RECORDING = True     # suppress FORCED logging while refinement is trying things out

def grow(tpl, parent_id, slot_name, depth, chain, placed, w, level, out):
    def add(tpl, parent=None, slot=None, depth=0, chain=()):
        node = {"_id": new_id(), "_tpl": tpl}
        if parent:
            node["parentId"] = parent; node["slotId"] = slot
        out.append(node)
        placed.add(tpl)
        if depth >= 6:
            return
        for s in sorted(db[tpl]["_props"].get("Slots", []),
                        key=lambda x: slot_rank(x.get("_name"))):
            if s["_name"] in SKIP:
                continue
            allowed = s["_props"]["filters"][0]["Filter"]
            # Widen in the original order: tier-legal first, then any usable part, then anything
            # at all - the last two only for required slots, as before.
            # A stock counts as must-fill even though the database marks it optional. At loyalty
            # level 1 no trader sells one for most guns, so the tier pool comes back empty and the
            # slot was simply skipped - leaving 55 builds with no shoulder stock at all. These
            # builds are explicitly the flea-fallback test, so a stock that has to come off the
            # flea is the expected answer, not a reason to go without.
            must = s["_required"] or (OPT["stock"] and is_stock_slot(s))

            tiers = [[c for c in allowed
                      if usable(c) and c not in chain
                      and loyalty.get(c) is not None and loyalty[c] <= level]]
            if must:
                tiers.append([c for c in allowed if usable(c) and c not in chain])
                tiers.append([c for c in allowed
                              if db.get(c) and db[c].get("_props") and c not in chain])

            # Exhaust every widening step looking for a compatible part before settling for a
            # conflicting one. Taking a conflicting tier-legal part when a compatible part exists
            # one step wider would defeat the whole fix.
            pool = next((ok for ok in ([c for c in t if compatible(c, placed)] for t in tiers) if ok), [])
            if not pool:
                if not must:
                    continue
                pool = next((t for t in tiers if t), [])
                if not pool:
                    continue
                if RECORDING:
                    FORCED.append(f"{name(tpl)}.{s['_name']}")
            pool = narrow(pool, s["_name"], placed)
            if not pool:
                continue      # narrow() can empty a slot on purpose - a second optic mount
            best = max(pool, key=lambda c: score(c, s["_name"], w))
            add(best, node["_id"], s["_name"], depth + 1, chain + (tpl,))
    add(tpl, parent_id, slot_name, depth, chain)

def _swap(items, node, alt, w, level):
    drop, changed = {node["_id"]}, True
    while changed:
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
    grow(alt, node["parentId"], node["slotId"], len(chain), tuple(chain), placed, w, level, sub)
    return keep + sub

def refine(items, w, level, rounds=3, breadth=6):
    """Greedy fills each slot knowing nothing about what follows, so an early pick can be a poor
    fit for the finished gun. Sweep it and keep any single swap that improves the whole weapon.

    Alternatives are restricted to what this loyalty tier can actually buy, so refinement cannot
    quietly smuggle in a part the tier was meant to exclude."""
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
                        if c != node["_tpl"] and usable(c)
                        and loyalty.get(c) is not None and loyalty[c] <= level]
                alts.sort(key=lambda c: score(c, node["slotId"], w), reverse=True)
                for alt in alts[:breadth]:
                    cand = _swap(best, node, alt, w, level)
                    if cand and shape_ok(cand, best, w) and objective(cand, w) > objective(best, w) + 1e-9:
                        best, improved = cand, True
                        break
                if improved:
                    break
            if not improved:
                break
    finally:
        RECORDING = was
    return best

# Categories that do a job the ergonomics/recoil numbers cannot express, so they earn their place
# even at a cost. Bipods are handled separately - see earns_place.
EARNS_PLACE = ("Collimator", "CompactCollimator", "OpticScope", "AssaultScope", "SpecialScope",
               "Flashlight", "TacticalCombo", "Silencer", "Magazine", "Stock", "Foregrip",
               "IronSight", "Barrel", "Receiver", "Handguard", "GasBlock",
               "PistolGrip", "ChargingHandle", "Launcher", "GrenadeLauncher")

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

def slot_required(parent_tpl, slot_name):
    for s in (db.get(parent_tpl, {}).get("_props") or {}).get("Slots", []) or []:
        if s.get("_name") == slot_name:
            return bool(s.get("_required"))
    return False

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

def make(weapon, level):
    global POLICY
    POLICY = optic_policy(weapon)
    w = weapon_weights(weapon)
    items, placed = [], set()
    grow(weapon, None, None, 0, (), placed, w, level, items)
    items = prune_empty(refine(items, w, level))
    stats = collections.Counter()
    for n in items[1:]:
        stats["buy_now" if buyable_now(n["_tpl"]) else "needs_flea"] += 1
    return items, stats

# ---- pick the weapons ----
if "--all" in sys.argv:
    guns, seen = [], {}
    for tpl, it in sorted(db.items(), key=lambda kv: name(kv[0])):
        if it.get("_type") != "Item" or not is_weapon(tpl):
            continue
        if not it["_props"].get("Slots"):
            continue
        s = short_name(tpl)
        seen[s] = seen.get(s, 0) + 1
        guns.append((tpl, s if seen[s] == 1 else f"{s} #{seen[s]}"))
else:
    guns = [(M4A1, short_name(M4A1))]

builds = []
totals = collections.Counter()
for tpl, short in guns:
    for level in (1, 2, 3, 4):
        items, stats = make(tpl, level)
        builds.append({
            "Id": new_id(),
            "Name": f"{short} - loyalty lvl {level} {TAG}",
            "Root": items[0]["_id"],
            "Items": items,
        })
        totals[f"L{level}_buy"]  += stats["buy_now"]
        totals[f"L{level}_flea"] += stats["needs_flea"]

print(f"{len(guns)} weapon(s) x 4 levels = {len(builds)} builds, "
      f"{sum(len(b['Items']) for b in builds):,} parts\n")
if FORCED:
    print(f"  {len(FORCED)} required slot(s) could only be filled with a conflicting part:")
    for f in sorted(set(FORCED)):
        print(f"    {f}")
    print()
print("  across all builds, parts that would come from each source:")
for level in (1, 2, 3, 4):
    b, f = totals[f"L{level}_buy"], totals[f"L{level}_flea"]
    tot = b + f or 1
    print(f"    loyalty lvl {level}: {b:>5} from your traders, {f:>5} off the flea  ({f*100//tot}% flea)")

if "--write" in sys.argv:
    prof = json.load(open(PROF, encoding="utf-8"))
    kept = [x for x in prof["userbuilds"]["weaponBuilds"] if TAG not in (x.get("Name") or "")]
    prof["userbuilds"]["weaponBuilds"] = kept + builds
    with open(PROF, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nWritten. kept {len(kept)} existing builds, added {len(builds)}.")
else:
    print("\n(preview only - pass --write to save)")
