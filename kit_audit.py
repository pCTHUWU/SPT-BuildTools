"""Audit generated equipment loadouts for parts that fit but are not worth fitting.

The weapon side grew seven checkers because every bug it found implied a family of siblings. The
equipment generator produced five bugs in one sitting with none, so this is the equivalent.

Reads the generator's output directly rather than the profile, so it works before anything is
written. Every count should read zero.

The first draft of this file reported 39 findings and every one was a false positive, which is
worth recording because each mistake was the same misunderstanding: **armour slots are zones**.
`Front_plate`, `Groin`, `Soft_armor_back` and `Helmet_ears` are different places on the body, so a
class-3 groin insert under a class-5 chest plate is not redundant - it is the only thing covering
the groin. A helmet reading `armorClass 0` is not dead weight either; it is a carrier, and its
plates hold the class. A rig with twelve small pouches is not badly fragmented; that is what a rig
*is*. Each check below is now written against what the thing is for.
"""
import io, os, sys, contextlib, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = ["make_equipment_builds.py", "--all"]
with contextlib.redirect_stdout(io.StringIO()):
    import make_equipment_builds as gen

from buildlib import db, name, loyalty

ARMOUR_SANITY = 6      # highest class a player can obtain; above this is boss or dev kit
TORSO = {"Front_plate", "Soft_armor_front"}


def obtainable(tpl):
    p = db[tpl]["_props"]
    return tpl in loyalty or p.get("CanSellOnRagfair") is not False


findings = collections.OrderedDict(
    (k, []) for k in ("torso uncovered", "missing essential", "dead weight", "unobtainable",
                      "absurd class", "fragmented backpack", "net-negative container",
                      "double armour"))

for b in gen.builds:
    items = b["Items"]
    root = items[0]["_id"]
    worn = [i for i in items if i.get("parentId") == root]
    slots_worn = {i.get("slotId") for i in worn}
    kids = collections.Counter(i.get("parentId") for i in items)

    # The one thing a loadout must do. Covered by the rig's plates or the body armour's, either is
    # fine - which is why this checks the whole tree rather than a particular carrier.
    if not any(i.get("slotId") in TORSO and gen.armor(i["_tpl"]) for i in items[1:]):
        findings["torso uncovered"].append((b["Name"], "no plate or soft armour on the chest"))

    # Necessary gear, per the user's definition. ArmorVest is exempt when the rig carries plates.
    rig = next((i for i in worn if i.get("slotId") == "TacticalVest"), None)
    rig_armoured = bool(rig and any(i.get("parentId") == rig["_id"] and gen.armor(i["_tpl"])
                                    for i in items))
    for need in ("Earpiece", "Headwear", "TacticalVest", "Backpack"):
        if need not in slots_worn:
            findings["missing essential"].append((b["Name"], f"no {need}"))
    if "ArmorVest" not in slots_worn and not rig_armoured:
        findings["missing essential"].append((b["Name"], "no body armour and the rig has no plates"))

    if rig_armoured and "ArmorVest" in slots_worn:
        findings["double armour"].append((b["Name"], "body armour worn under an armoured rig"))

    for i in items[1:]:
        tpl, slot = i["_tpl"], i.get("slotId")
        a, s, wt = gen.armor(tpl), gen.storage(tpl), gen.weight(tpl)

        # Carries nothing, protects nothing, holds nothing, and is not required kit.
        if (not a and not s and wt > 0.1 and not kids[i["_id"]]
                and slot not in gen.ESSENTIAL):
            findings["dead weight"].append((b["Name"], f"{name(tpl)[:38]} {wt:.2f}kg"))

        if not obtainable(tpl):
            findings["unobtainable"].append((b["Name"], name(tpl)[:38]))

        if a > ARMOUR_SANITY:
            findings["absurd class"].append((b["Name"], f"{name(tpl)[:38]} class {a:.0f}"))

        if s:
            # Only backpacks: a rig is *meant* to be many small pouches. A big pack that cannot
            # take a big item is the real fault.
            if slot == "Backpack" and s >= 24 and gen.biggest(tpl) <= 8:
                findings["fragmented backpack"].append(
                    (b["Name"], f"{name(tpl)[:38]} {s:.0f} cells, largest {gen.biggest(tpl):.0f}"))
            if gen.net_cells(tpl) < 0:
                findings["net-negative container"].append(
                    (b["Name"],
                     f"{name(tpl)[:38]} holds {s:.0f}, occupies {gen.footprint(tpl):.0f}"))

print(f"kit_audit - {len(gen.builds)} loadout(s)\n")
total = 0
for k, v in findings.items():
    print(f"  {k:<24} {len(v)}")
    total += len(v)
    for nm, detail in v[:4]:
        print(f"       {nm[:26]:<28} {detail}")
    if len(v) > 4:
        print(f"       ... and {len(v)-4} more")
print(f"\ntotal findings: {total}")
