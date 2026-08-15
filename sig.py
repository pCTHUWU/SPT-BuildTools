"""Structural signature of a generator's output, for proving a refactor changed nothing.

Item _ids are random per run, so the signature is built from the tree's *shape*: for every part,
the slot it sits in, its template, and its parent's template. Sorted, so ordering cannot mask a
difference. Usage:  python sig.py <make_builds|make_loyalty_builds> [gen args...]
"""
import io, os, sys, contextlib, hashlib

REPO = r"C:\Claude Code\profile-tools"
mod_name = sys.argv[1]
sys.argv = [mod_name + ".py"] + sys.argv[2:]
sys.path.insert(0, REPO)
os.chdir(REPO)

with contextlib.redirect_stdout(io.StringIO()):
    mod = __import__(mod_name)

for b in mod.builds:
    by = {i["_id"]: i for i in b["Items"]}
    rows = sorted(
        "{}|{}|{}".format(
            i.get("slotId") or "-",
            i["_tpl"],
            by[i["parentId"]]["_tpl"] if i.get("parentId") in by else "-",
        )
        for i in b["Items"]
    )
    digest = hashlib.sha1("\n".join(rows).encode()).hexdigest()[:12]
    print("{}\t{}\t{}".format(b["Name"], len(b["Items"]), digest))
