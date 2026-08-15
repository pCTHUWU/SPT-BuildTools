"""What does the database expose for optic magnification, suppressors and light/laser combos?"""
import io, json
from collections import Counter

items = json.load(io.open(r"C:\SPT\SPT_Runtime\SPT_Data\database\templates\items.json", encoding="utf-8"))
byname = {v.get("_name"): k for k, v in items.items()}

_c = {}
def cats(t):
    if t not in _c:
        o, cur, n = [], items.get(t), 0
        while cur and n < 14:
            o.append(cur.get("_name") or ""); cur = items.get(cur.get("_parent")); n += 1
        _c[t] = o
    return _c[t]

print("=== optic-ish categories present, with a sample and its zoom fields ===")
seen = {}
for tpl, it in items.items():
    if it.get("_type") != "Item":
        continue
    c = cats(tpl)
    for want in ("CompactCollimator", "Collimator", "OpticScope", "AssaultScope", "SpecialScope"):
        if want in c and want not in seen:
            p = it.get("_props") or {}
            seen[want] = (it.get("_name"), p.get("Zooms"), p.get("ModesCount"),
                          p.get("CalibrationDistances") is not None)
for k, v in seen.items():
    print(f"  {k:<18} e.g. {v[0][:44]:<44} Zooms={v[1]} ModesCount={v[2]}")

print("\n=== how many optics are variable (more than one zoom level)? ===")
tot = var = 0
examples = []
for tpl, it in items.items():
    if it.get("_type") != "Item":
        continue
    c = cats(tpl)
    if not any(x in c for x in ("CompactCollimator", "Collimator", "OpticScope", "AssaultScope", "SpecialScope")):
        continue
    z = (it.get("_props") or {}).get("Zooms")
    tot += 1
    flat = []
    if isinstance(z, list):
        for row in z:
            flat += row if isinstance(row, list) else [row]
    if len(set(flat)) > 1:
        var += 1
        if len(examples) < 8:
            examples.append((it.get("_name"), sorted(set(flat))))
print(f"  {var} of {tot} optics have more than one zoom level")
for n, f in examples:
    print(f"     {n[:52]:<52} zooms {f}")

print("\n=== suppressors ===")
sil = [t for t, it in items.items() if it.get("_type") == "Item" and "Silencer" in cats(t)]
print(f"  Silencer category items: {len(sil)}")
print("  sample:", ", ".join((items[t].get('_name') or '')[:34] for t in sil[:4]))

print("\n=== light vs light+laser combo ===")
for want in ("Flashlight", "TacticalCombo", "CombTactical", "LaserDesignator"):
    got = [t for t, it in items.items() if it.get("_type") == "Item" and want in cats(t)]
    print(f"  {want:<16} {len(got):>3}   e.g. {(items[got[0]].get('_name') if got else '-')[:44]}")

print("\n=== weapon calibers in use ===")
cal = Counter()
for tpl, it in items.items():
    if it.get("_type") == "Item" and "Weapon" in cats(tpl):
        c = (it.get("_props") or {}).get("ammoCaliber")
        if c:
            cal[c] += 1
for c, n in cal.most_common(20):
    print(f"  {n:>3}  {c}")
