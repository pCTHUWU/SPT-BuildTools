"""Compare finished-weapon stats between two profile snapshots, matched by build name."""
import io, json, sys

ITEMS = r"C:\SPT\SPT_Runtime\SPT_Data\database\templates\items.json"
items = json.load(io.open(ITEMS, encoding="utf-8"))

def stats(its):
    p = items[its[0]["_tpl"]]["_props"]
    ergo = p.get("Ergonomics", 0) or 0
    pct = 0.0
    for n in its[1:]:
        mp = items[n["_tpl"]]["_props"]
        ergo += mp.get("Ergonomics", 0) or 0
        pct += mp.get("Recoil", 0) or 0
    return ergo, (p.get("RecoilForceUp", 0) or 0) * (1 + pct / 100.0), pct

def load(path):
    prof = json.load(io.open(path, encoding="utf-8"))
    return {b["Name"]: b for b in prof["userbuilds"]["weaponBuilds"]}

old, new = load(sys.argv[1]), load(sys.argv[2])
shared = sorted(set(old) & set(new))
print(f"comparing {len(shared)} builds present in both\n")

de = dr = 0.0
better_e = better_r = worse_e = worse_r = 0
rows = []
for n in shared:
    oe, ou, op = stats(old[n]["Items"])
    ne, nu, np_ = stats(new[n]["Items"])
    de += ne - oe
    dr += np_ - op
    if ne > oe: better_e += 1
    elif ne < oe: worse_e += 1
    if np_ < op: better_r += 1
    elif np_ > op: worse_r += 1
    rows.append((ne - oe, np_ - op, n, oe, ne, op, np_))

print(f"ergonomics   : {de/len(shared):+.1f} average   ({better_e} better, {worse_e} worse)")
print(f"recoil %     : {dr/len(shared):+.1f} average   ({better_r} better, {worse_r} worse)")
print(f"   (recoil is a reduction percentage - more negative is better)\n")

rows.sort(key=lambda r: r[0])
print("biggest ergonomics losses:")
for d, dp, n, oe, ne, op, np_ in rows[:5]:
    print(f"  {n:<34} ergo {oe:>4.0f}->{ne:<4.0f}  recoil {op:>+5.0f}%->{np_:<+5.0f}%")
print("\nbiggest ergonomics gains:")
for d, dp, n, oe, ne, op, np_ in rows[-5:]:
    print(f"  {n:<34} ergo {oe:>4.0f}->{ne:<4.0f}  recoil {op:>+5.0f}%->{np_:<+5.0f}%")

rows.sort(key=lambda r: r[1])
print("\nbiggest recoil improvements:")
for d, dp, n, oe, ne, op, np_ in rows[:5]:
    print(f"  {n:<34} recoil {op:>+5.0f}%->{np_:<+5.0f}%  ergo {oe:>4.0f}->{ne:<4.0f}")
