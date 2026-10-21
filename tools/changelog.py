import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapt

EMPTY = {"targets": [], "device_tested": []}
GENERATED = (
    "targets.json",
    "SUPPORTED.md",
    "gradle.properties",
    "app/src/main/java/com/usmanzade/gmx/Targets.java",
)
NOISE = re.compile(r"^(Merge |Revert \"Merge )")

def warn(message):
    print("changelog: " + message, file=sys.stderr)

def git(args, cwd, check=True):
    out = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and out.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(args), out.stderr.strip()))
    return out.stdout

def vkey(tag):
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"[.\-]", tag.lstrip("v"))]

def previous_tag(tag, cwd):
    tags = [t for t in git(["tag", "--list", "v*"], cwd).split() if t != tag]
    older = [t for t in tags if vkey(t) < vkey(tag)]
    return max(older, key=vkey) if older else None

def targets_at(ref, cwd):
    out = subprocess.run(["git", "show", "%s:targets.json" % ref], cwd=cwd, capture_output=True, text=True,
                         encoding="utf-8")
    if out.returncode != 0:
        return dict(EMPTY)
    try:
        data = json.loads(out.stdout)
        if not isinstance(data.get("targets"), list):
            raise ValueError('no "targets" list')
        return data
    except json.JSONDecodeError as err:
        warn("%s: %s" % (ref, adapt.describe_json_error(out.stdout, err)))
    except ValueError as err:
        warn("%s: targets.json is unusable: %s" % (ref, err))
    return None

def commits(prev, ref, cwd):
    rng = "%s..%s" % (prev, ref) if prev else ref
    out = git(["log", rng, "--no-merges", "--pretty=format:@@%s", "--name-only"], cwd)
    result, subject, files = [], None, []
    for line in out.splitlines() + ["@@"]:
        if line.startswith("@@"):
            if subject is not None and not NOISE.match(subject):
                result.append((subject, files))
            subject, files = line[2:], []
        elif line.strip():
            files.append(line.strip())
    return [(s, f) for s, f in result if s]

def builds(data):
    return {ver for t in data["targets"] for v in t["variants"] for ver in v["versions"]}

def affects_module(files):
    return any(f.startswith("app/src/main/") and f not in GENERATED for f in files)

def render(new, old, subjects, first=False):
    notes = []
    tested = set(new.get("device_tested", [])) if new is not None else set()

    def label(build):
        return build if build in tested else "%s (not device-tested)" % build

    if first:
        found = sorted(builds(new), key=vkey, reverse=True) if new is not None else []
        notes.append("Initial release." + (" Supports Graph Messenger %s." % ", ".join(map(label, found)) if found else ""))
    else:
        if new is not None and old is not None:
            for build in sorted(builds(new) - builds(old), key=vkey):
                notes.append("Added support for Graph Messenger %s." % label(build))
        notes.extend(subject for subject, files in subjects if affects_module(files))
    notes = list(dict.fromkeys(notes)) or ["No user-facing changes."]
    return "".join("- %s\n" % n for n in notes)

def main(argv=None):
    p = argparse.ArgumentParser(prog="changelog.py")
    p.add_argument("--tag", required=True, help="release tag, for example v1.0.1")
    p.add_argument("--prev", help="previous tag (default: the newest older v* tag)")
    p.add_argument("--ref", default="HEAD", help="commit the release is built from")
    p.add_argument("--repo-dir", default=".")
    a = p.parse_args(argv)
    try:
        prev = a.prev or previous_tag(a.tag, a.repo_dir)
    except SystemExit as err:
        warn(str(err))
        prev = None
    new = targets_at(a.ref, a.repo_dir)
    old = targets_at(prev, a.repo_dir) if prev else dict(EMPTY)
    if new is None:
        warn("supported builds are left out of these notes")
    try:
        subjects = commits(prev, a.ref, a.repo_dir)
    except SystemExit as err:
        warn(str(err))
        subjects = []
    sys.stdout.write(render(new, old, subjects, first=prev is None))
    return 0

if __name__ == "__main__":
    sys.exit(main())
