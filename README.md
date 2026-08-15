# Profile tools

Scripts that generate and check the weapon builds in the SPT profile
(`C:\SPT\SPT_Runtime\user\profiles\6a751c000164cc5fb0ccc217.json`).

They live here rather than in a session scratchpad because scratchpads are per-session and these
were already lost once that way. Nothing here is published — see the never-publish list in
`~/.claude/SESSION-LOG.md`.

| Script | What it does |
|---|---|
| `make_builds.py --all [--write]` | 152 `(meta)` builds, one per weapon. Best part per slot by `Ergonomics - Recoil`, magazines by capacity. |
| `make_loyalty_builds.py --all [--write]` | 608 `(LL)` builds — 152 weapons × 4 loyalty tiers, restricted to parts each tier can actually buy. |
| `validate_builds.py [out.json]` | Checks every build in the profile for conflicts and bad slots. |
| `stock_real.py` | Checks no build ended up without a shoulder stock. |
| `sights_lights.py` | Counts sights and light sources per build across profile snapshots. |
| `compare_stats.py <old.json> <new.json>` | Finished-weapon ergo/recoil between two profile snapshots. |
| `inspect_build.py "<build name>"` | Dumps one build as a tree and explains its conflicts. |

**Run both checkers after any change.** They pull in opposite directions — conflict-avoidance
wants to leave slots empty, must-fill wants them filled — and a change that fixes one usually
breaks the other. Passing both is the bar: `validate_builds.py` at 0 failures and `stock_real.py`
at 0 stockless.

Both generators preview by default and only touch the profile with `--write`. They replace only
builds carrying their own tag, so running one does not disturb the other's.

## The trap these scripts exist to avoid

A part being allowed by a slot's own filter does **not** make it legal. `_props.Slots[].filters[]
.Filter` governs one slot in isolation; `_props.ConflictingItems` is a separate, weapon-wide rule —
a railed dust cover excluding the standard rear sight, a grip with an integrated stock excluding a
separate stock, a handguard longer than the barrel beneath it.

Choosing the best part per slot independently, which is what these scripts did originally, produced
**442 conflicts across 248 of 760 builds** while achieving a perfect score on slot filters. Those
builds refuse to assemble in the build screen. Fixed 2026-08-14.

Two things worth knowing before touching the selection logic:

- **`ConflictingItems` is recorded one-directionally.** The handguard names the barrel; the barrel
  does not name the handguard. Check `A.conflicts ∩ placed` *and* `any(A in p.conflicts)`, or you
  will find roughly half of them and believe you are done.
- **Prefer a compatible part from a wider candidate pool over a conflicting one from the ideal
  pool.** In the loyalty generator that means exhausting every widening step looking for something
  compatible before settling. Getting this backwards silently reintroduces the bug for required
  slots only, which is exactly the kind of thing that survives a casual test.

## Three more traps, all hit while fixing the first one

- **Sibling slot order decides who wins a contested pair.** Several "pistol grips" — the Hera Arms
  CQR family — are grips with an integrated stock, and they conflict with every real stock. Filling
  the grip first left rifles with a bare buffer tube and no stock: perfectly legal, and useless.
  `slot_rank()` fills the stock chain first so the grip falls back to an ordinary compatible one.
- **A stock must be treated as must-fill even though the database marks it optional.** At loyalty
  level 1 no trader sells one for most guns, so the tier pool came back empty and the slot was
  skipped — 55 builds with no stock at all. These builds are the flea-fallback test, so a stock
  bought off the flea is the expected answer.
- **`is_stock_slot()` needs the slot name *and* the recoil test, not either alone.** By name only,
  a butt pad slot on a wooden AK stock is also `mod_stock`. By recoil only, muzzle brakes,
  compensators and suppressors all cut recoil by 15+ — testing recoil on its own silently made
  every muzzle must-fill and forced 27 conflicting muzzle devices into builds.

Run `validate_builds.py` and `stock_real.py` after any change to either generator. Both should
report zero. Use `compare_stats.py` against the pre-change backup to check the builds actually got
better rather than merely different.

## Owner's preferences

Encoded in `narrow()` in both generators, because none of it can be expressed as ergonomics or
recoil — every one of these costs points on both, so refinement would trade them all away if
`shape_ok()` did not hold them.

- **Suppressed.** Any `mod_muzzle*` slot prefers a `Silencer`. Barrels are also steered toward
  suppressor-compatible ones (`suppressor_friendly`), because a short barrel that conflicts with
  every silencer settles the question before the muzzle slot is ever reached.
- **Light/laser combo.** The first tactical slot goes to a `TacticalCombo` (the AN/PEQ family) in
  preference to a bare torch. Note `CombTactical` and `LaserDesignator` are empty categories here
  and there are only 3 plain `Flashlight` items — combos are the 20 that matter.
- **Sight to suit the calibre.** Pistol-calibre and shot get a non-magnified dot; intermediate
  rifle rounds get the 1-4x class, ideally one that toggles; full-power and magnum get a scope,
  variable first. Driven by the weapon's `ammoCaliber`.

**Judge an optic by its category, not by `Zooms`.** That field gives the magnification value but
does not reliably mark a scope as variable — the Nightforce NXS 2.5-10x24 reports a flat `[[1]]`.
`Collimator`/`CompactCollimator` are dots, `AssaultScope` is the 1-4x class, `OpticScope` is a full
scope (15 of 24 variable). An early attempt keyed on `Zooms` alone and changed nothing at all.

**Prefer the optic, keep the mounts.** Filtering a scope slot down to just the wanted optics breaks
the only path to a sight on some guns, since the mount is how the optic attaches. `narrow()` drops
unwanted optics but keeps any mount that `can_carry_optic()` says leads to a wanted one.

Red dots surviving on rifles are almost all `loyalty lvl 1` builds, where no trader sells a
magnified optic yet. That is correct tier behaviour, not a miss.

## How parts are chosen

Two stages.

**Greedy fill** takes the best-scoring candidate for each slot, where the score weights ergonomics
against recoil *by what the gun is for* — read from `weapFireType`, not guessed from category
names. Full-auto weights recoil at 2× and ergonomics at 1×; everything else 1.8× / 0.8×. The
original `Ergonomics - Recoil` weighted them equally on every weapon, which took a +21 ergo stock
over a −18 recoil one on an assault rifle and paid for recoil control on a bolt-action that fires
once every few seconds.

**Refinement** then sweeps the finished weapon and tries swapping each part for its alternatives,
keeping any change that improves the whole gun. Greedy fills each slot knowing nothing about what
comes after it, so an early pick can be a poor fit for the finished build. In the loyalty
generator, refinement is restricted to parts that tier can actually buy, so it cannot smuggle in
something the tier was meant to exclude.

Measure with `compare_stats.py`, not by eye. Against the pre-optimisation builds this was **+7.0
ergonomics on average (494 better, 45 worse)** with recoil roughly flat overall — but that average
hides the point: semi-autos and bolt-actions traded recoil they did not need for large ergonomics
gains (SR-25 35→74), while full-autos went the other way (MCX .300 BLK −33%→−45%). Builds that got
"worse" on ergonomics are almost all full-autos that bought recoil with it, which is the intent.

Beware of reading a raw part count as quality: the count fell when this landed, because refinement
drops parts that do not earn their place.

## Before writing to the profile

Check `EscapeFromTarkov` and `SPT.Server` are not running, and take a `.bak-<reason>` copy of the
profile first — the generators overwrite it in place.
