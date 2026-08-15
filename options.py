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
