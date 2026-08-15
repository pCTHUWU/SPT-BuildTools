# SPT build tools

> ## 🤖 Written by AI
>
> **Effectively all of this — the design, the code, the debugging and these docs — was written by
> Claude (Anthropic).** I set the goals, ran it in the game, and reported what broke; the AI did the
> engineering. That includes the parts that were wrong at first, and the fixes for them.
>
> This is stated plainly because you should know what you are running. Read the source before you
> trust it with a profile you care about, and keep backups.

Generates weapon builds into an SPT profile, and checks them. Python 3 only — tkinter ships with
Python, so there is nothing to install.

```
python build_gui.py          # the GUI
python make_builds.py --all  # or just run the generators
```

**This writes to your profile.** Close the game and the server first, keep the backup option on,
and preview before you write.

## The GUI

`build_gui.py` is deliberately thin. It builds the same command line the scripts already accept and
shows their output — no build logic lives in it, so the scripts stay usable alone and there is only
one place for the rules. It refuses to write while `EscapeFromTarkov.exe` or `SPT.Server.exe` is
running, and takes a timestamped profile backup first.

## Toggles

| Toggle | Off means |
|---|---|
| Respect part conflicts | Ignore `ConflictingItems`. Produces builds the game refuses to assemble — it is there to show what the rule is worth, not as a normal setting. |
| Shortest route to the sight *(off by default)* | On, the sight mounts directly where it fits and otherwise takes the shortest chain. It does clear the mount towers, but it also cost rifle-calibre builds 58 magnified optics in testing and the cause is not yet understood - see below. |
| Drop parts that earn nothing | Off, 413 mounts and rails stay fitted while carrying nothing and giving nothing — an Aimpoint spacer with no Aimpoint on it, 258 times. Bipods are kept on bolt-actions, marksman rifles and machine guns, and dropped from anything else. |
| Fit underbarrel launchers *(off by default)* | On, a GP-25 or M203 gets hung under anything that takes one. It conflicts with 72 other parts, so 43 of the 57 builds that had one carried no foregrip at all. Weapons that *are* launchers are unaffected. |
| Only use parts sellable on the flea *(off by default)* | On, every part must be `CanSellOnRagfair`. Availability that matters is the trader level a build describes, and meta builds assume max standing — so this is off. Turn it on only to exercise a flea-buying mod. |
| Always fit a stock | 55 builds end up with no shoulder stock. |
| One optic per gun | About a third of builds carry two or more sights. |
| Match optic to calibre | The ergonomics score picks a red dot for nearly everything. |
| Prefer suppressed | Muzzle devices chosen on stats alone. |
| Fit a light/laser combo | Lights score zero on ergonomics and recoil, so they lose every contest. |
| No magazines wider than 2 slots | Drums and long extendeds get fitted. 80 builds carried an oversized magazine that had a smaller alternative. |
| Capacity only matters on automatics | Bolt-actions and semi-autos reach for the biggest magazine they can take, paying ergonomics and length for rounds they will not fire. |
| Refine the finished gun | Parts are chosen per slot with no view of the finished weapon. |

Everything defaults on. Flags follow the same names: `--no-suppressor`, `--no-refine`, and so on.

## Scripts

| Script | What it does |
|---|---|
| `make_builds.py --all [--write]` | 152 meta builds, one per weapon. |
| `make_loyalty_builds.py --all [--write]` | 608 builds — 152 weapons × 4 loyalty tiers, restricted to what each tier can buy. |
| `validate_builds.py` | Conflicts, bad slots, orphans. Should report zero. |
| `stock_real.py` | Builds left without a shoulder stock. Should report zero. |
| `sights_lights.py` | Sights and light sources per build. |
| `prefs_audit.py` | Whether the preferences actually landed. |
| `mount_audit.py` | What each build pays to mount its sight, and how long the chain is. |
| `slot_audit.py` | Slots filled for no gain - empty mounts, dead weight, hopeless slots. |
| `probe_launchers.py` | Where launchers get fitted and what they displace. |
| `compare_stats.py <old> <new>` | Finished-weapon ergonomics and recoil between two profile snapshots. |
| `inspect_build.py "<name>"` | One build as a tree, with its conflicts explained. |

Both generators preview unless given `--write`, and replace only builds carrying their own tag, so
running one does not disturb the other's.

## Paths

Defaults to `C:\SPT\SPT_Runtime` and the only profile in `user\profiles`. Override with:

- `SPT_ROOT` — environment variable, if SPT is installed elsewhere
- `SPT_PROFILE` — environment variable, or `--profile <path>` if you have more than one

## Run both checkers after any change

`validate_builds.py` and `stock_real.py` pull in opposite directions — conflict-avoidance wants
slots empty, must-fill wants them filled — and a change that fixes one routinely breaks the other.
Both at zero is the bar. Use `compare_stats.py` against the pre-change backup to confirm the builds
got better rather than merely different.

## What this learned the hard way

Each of these cost a round of broken builds.

**A slot's own filter is not the whole story.** `_props.Slots[].filters[].Filter` governs one slot
in isolation; `_props.ConflictingItems` is a separate, weapon-wide rule. Choosing the best part per
slot independently scored perfectly on slot filters and still produced **442 conflicts across 248 of
760 builds**.

**`ConflictingItems` is recorded one-directionally.** The handguard names the barrel; the barrel does
not name the handguard. Check both directions or you find about half and believe you are done.

**Sibling slot order decides contested pairs.** Several "pistol grips" — the Hera Arms CQR family —
are grips with an integrated stock and conflict with every real stock. Filling the grip first left
rifles with a bare buffer tube and no stock: legal, and useless.

**Detecting a stock slot needs the name *and* a recoil test.** By name alone, a butt pad slot on a
wooden AK stock is also `mod_stock` (−1 recoil, versus −15 to −24 for a real stock). By recoil alone,
muzzle brakes and suppressors also cut recoil by 15+ — testing recoil on its own silently made every
muzzle must-fill and forced 27 conflicting muzzle devices into builds.

**Judge an optic by category, not by `Zooms`.** That field gives magnification but does not reliably
mark a scope as variable — the Nightforce NXS 2.5-10x24 reports a flat `1x`. `Collimator` and
`CompactCollimator` are dots, `AssaultScope` is the 1-4x class, `OpticScope` is a full scope. A first
attempt keyed on `Zooms` alone produced byte-identical output.

**Prefer the optic, keep the mounts.** Filtering a scope slot down to the optics you want breaks the
only path to a sight on guns where the mount carries it.

**Mod `Recoil` values are percentages** applied to the weapon's own `RecoilForceUp`/`Back`. They sum
and then scale, so they are not additive with ergonomics and cannot be compared part-by-part.

**Refinement cannot see magazine capacity**, because `objective` is only ergonomics and recoil. Left
to itself it put a 40-round three-slot PMAG on the M4A1 when a two-slot 60-round magazine was
available — worse on both counts, but better on ergonomics. `shape_ok` now refuses any swap that
grows the magazine's footprint, or that shrinks its capacity on an automatic.

**A part that fits is not a part worth fitting.** This has now caused four separate bugs - stacked
optics, oversized magazines, grenade launchers, and 413 mounts holding air. Depth-first filling
cannot know whether a rail earns its place until its children have been tried, so `prune_empty`
cleans up afterwards rather than trying to predict it. Run `slot_audit.py` to find the next one.

**The launcher case.** `mod_launcher` accepts nothing but launchers, so
the generator dutifully hung a GP-25 under 57 builds. It conflicts with 72 other parts, and 43 of
those builds ended up with no foregrip. Leaving the slot empty costs nothing and gave 32 builds
their grip back. Worth asking of any slot: what does filling it actually buy?

**Availability means the trader level, not the flea.** `usable` used to require every part be
`CanSellOnRagfair`, which silently excluded good kit — the SureFire MAG5-60 and the PMAG D-60 among
it — and made the best two-slot magazine look worse than it is. A part needs to be purchasable at
the trader level a build describes; meta builds assume max standing and full availability. The old
behaviour survives as the `flea-only` toggle, off by default, for when the builds are being used to
exercise a flea-buying mod.

## An unfinished one: mount towers

`mount_audit.py` shows 15 builds stacking three or more mounting parts under one sight. The VSK-94
took four - a dovetail adapter, a rail base, a riser and scope rings - and because mount plates read
*positive* on ergonomics, the chain netted +1.5, so nothing in the objective ever objected.

The `short-mounts` toggle addresses it and does remove every tower. It also cost rifle-calibre
builds 58 of their magnified optics (83 scopes down to 15), which is a worse trade than the towers
it fixes. Capping the chain at two parts, capping at three, and fixing a memoisation cycle guard all
left the numbers byte-identical, so whatever decides those slots is somewhere this has not looked
yet. Off by default until that is understood.

## How parts are chosen

Greedy fill takes the best-scoring candidate per slot, weighting ergonomics against recoil by what
the gun is for — read from `weapFireType`, not guessed from category names. Full-auto weights recoil
2× and ergonomics 1×; everything else 1.8× / 0.8×.

Refinement then sweeps the finished weapon swapping parts for alternatives, keeping any change that
improves the whole gun, since greedy filling cannot see past the slot it is on. In the loyalty
generator refinement is capped to parts that tier can actually buy.

Do not read a raw part count as quality — refinement drops parts that do not earn their place.
