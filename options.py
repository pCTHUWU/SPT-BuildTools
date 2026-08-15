"""Toggles shared by both generators and the GUI.

Read off the command line, so the scripts stay usable on their own and the GUI is nothing more
than something that builds the same command line. `--no-<name>` turns a preference off,
`--<name>` turns it on, absent means the default below.

Order here is the order the GUI shows them in.
"""
import glob
import os
import sys

# Where SPT lives. Override with the SPT_ROOT environment variable if yours is elsewhere.
SPT_ROOT = os.environ.get("SPT_ROOT", r"C:\SPT\SPT_Runtime")
DB_DIR = os.path.join(SPT_ROOT, "SPT_Data", "database")
ITEMS = os.path.join(DB_DIR, "templates", "items.json")
LOCALE = os.path.join(DB_DIR, "locales", "global", "en.json")
PROFILE_DIR = os.path.join(SPT_ROOT, "user", "profiles")


def resolve_profile():
    """Find the profile to work on.

    Was hardcoded to one account's GUID, which is fine on the machine it was written for and
    useless anywhere else. Order: an explicit --profile argument, then the SPT_PROFILE
    environment variable, then the only profile in the folder.
    """
    if "--profile" in sys.argv:
        return sys.argv[sys.argv.index("--profile") + 1]

    env = os.environ.get("SPT_PROFILE")
    if env:
        return env

    found = [p for p in glob.glob(os.path.join(PROFILE_DIR, "*.json"))
             if not os.path.basename(p).startswith(".")]
    if len(found) == 1:
        return found[0]
    if not found:
        raise SystemExit(
            f"No profile found in {PROFILE_DIR}.\n"
            "Set SPT_ROOT if SPT is installed elsewhere, or pass --profile <path>.")
    raise SystemExit(
        "More than one profile here, so pick one explicitly with --profile <path>:\n  "
        + "\n  ".join(os.path.basename(p) for p in found))

# name -> (default, label, explanation shown in the GUI)
TOGGLES = [
    ("conflicts", True,
     "Respect part conflicts",
     "Honour ConflictingItems. Turning this off produces builds the game will refuse to "
     "assemble - it is here to show what the rule is worth, not as a normal setting."),

    ("stock", True,
     "Always fit a stock",
     "Treat a shoulder stock as required even where the database marks it optional. Off, 55 "
     "builds end up with no stock at all."),

    ("one-optic", True,
     "One optic per gun",
     "Leave a second scope mount empty rather than stacking sights. Off, about a third of "
     "builds carry two or more."),

    ("optic-policy", True,
     "Match optic to calibre",
     "Non-magnified on pistol-calibre and shot, the 1-4x class on intermediate rifle rounds, a "
     "scope on full-power. Off, the ergonomics score picks a red dot for nearly everything."),

    ("suppressor", True,
     "Prefer suppressed",
     "Take a silencer wherever the muzzle accepts one, and prefer barrels that leave that "
     "option open."),

    ("light", True,
     "Fit a light/laser combo",
     "Give the first tactical slot to a light, preferring an AN/PEQ-style combo over a bare "
     "torch. These score zero on ergonomics and recoil, so without this they always lose."),

    ("short-mounts", False,
     "Shortest route to the sight",
     "Mount the sight directly where it fits, and otherwise take the shortest mount chain, scoring "
     "each route by the best sight it reaches against the parts needed to get there.\n\n"
     "**This no longer owns the tower problem.** Mount plates score positively on ergonomics, so "
     "the optimiser was rewarded for stacking them - the VSK-94 wore four under one scope. That is "
     "now capped unconditionally in `narrow()` at `MAX_MOUNTS`, whatever this toggle says. The cap "
     "used to live behind this flag, which is why capping the chain and fixing the memo both left "
     "the numbers byte-identical: with the toggle off, none of that code ran at all.\n\n"
     "OFF by default because the route *scoring* here still costs rifle-calibre builds 58 of their "
     "magnified optics (83 scopes down to 15), and that cause is genuinely not understood yet. "
     "Capping and choosing are separate concerns; only the choosing is still in question."),

    ("prune-empty", True,
     "Drop parts that earn nothing",
     "After building, remove any mount or rail left carrying nothing that also gives no "
     "ergonomics or recoil. Depth-first filling cannot know whether a rail earns its place until "
     "its children have been tried - 413 ended up holding air, including an Aimpoint spacer with "
     "no Aimpoint on it 258 times. Required slots are left alone."),

    ("launchers", False,
     "Fit underbarrel launchers",
     "Off by default. mod_launcher accepts nothing but launchers, so leaving it empty costs "
     "nothing - and the GP-25 alone conflicts with 72 other parts, which left 43 of the 57 builds "
     "that had one with no foregrip at all. A grip and a light beat a grenade you carry no rounds "
     "for. Weapons that ARE launchers are unaffected; this only governs hanging one under "
     "another gun."),

    ("flea-only", False,
     "Only use parts sellable on the flea",
     "Off by default: a part needs to be purchasable at the trader level a build describes, and "
     "meta builds assume max trader standing and full availability. Turning it on restricts every "
     "part to `CanSellOnRagfair`, which is what you want if the builds are being used to exercise "
     "a flea-buying mod - but it excludes plenty of good kit, the SureFire MAG5-60 among it."),

    ("compact-mags", True,
     "No magazines wider than 2 slots",
     "Skip magazines that take 3 or more grid slots. An extended magazine that still fits in the "
     "usual 2 is fine - the AK-74N takes a 60-round 6L31 in two slots, where the 3-slot option "
     "holds only 45. Where a gun has nothing smaller the rule gives way rather than leaving it "
     "unfed, which is the case for 22 builds. Note some famous 2-slot extendeds (the SureFire "
     "MAG5-60) are not flea-obtainable in this version and are excluded by `usable` first."),

    ("mag-capacity", True,
     "Magazine capacity only matters on automatics",
     "On a bolt-action or semi-auto the extra rounds buy little and cost ergonomics and length, "
     "so magazines there are judged on handling like any other part. Off, every gun reaches for "
     "the biggest magazine it can take."),

    ("pareto", False,
     "Pick from a Pareto frontier (UNFINISHED)",
     "Build several candidates per gun across a range of ergonomics-versus-recoil weightings, "
     "keep the ones nothing else beats outright on ergonomics, accuracy and vertical recoil, and "
     "take the knee of that set. One fixed weighting bakes the same trade into every weapon and it "
     "is the wrong trade at both ends. Also decides the suppressor: a can that costs more "
     "ergonomics than it is worth loses to the loud build rather than overriding it.\n\n"
     "OFF and UNFINISHED: only make_builds.py implements it, so turning it on would have the meta "
     "and loyalty generators choosing parts by different rules. Port it to make_loyalty_builds.py "
     "before switching this on. Results so far look strong - M4A1 ergonomics 68 to 116 at "
     "identical recoil, G36 28 to 80 - but the ergonomics figure needs checking against the "
     "in-game number first: a raw sum of 116 against db4tarkov's 65.6 suggests the two are not "
     "the same scale, even though recoil matches exactly."),

    ("refine", True,
     "Refine the finished gun",
     "After building, sweep the weapon swapping parts for alternatives and keep anything that "
     "improves it as a whole. Greedy filling alone cannot see past the slot it is on."),
]

DEFAULTS = {name: default for name, default, _, _ in TOGGLES}


def _flag(name, default):
    if f"--no-{name}" in sys.argv:
        return False
    if f"--{name}" in sys.argv:
        return True
    return default


OPT = {name: _flag(name, default) for name, default, _, _ in TOGGLES}
