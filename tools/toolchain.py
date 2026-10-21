import argparse
import re
import sys

def parse(version, parts):
    numbers = re.findall(r"\d+", version)
    if len(numbers) < parts:
        raise ValueError("cannot read %d numeric component(s) from %r" % (parts, version))
    return tuple(int(n) for n in numbers[:parts])

def read_version(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()

def compare(current, latest, parts):
    return parse(latest, parts) > parse(current, parts)

def cmd_compare(args):
    current = read_version(args.file)
    newer = compare(current, args.latest, args.parts)
    print("current=%s" % current)
    print("latest=%s" % args.latest)
    print("newer=%s" % ("true" if newer else "false"))
    return 0

def cmd_bump(args):
    parse(args.version, 1)
    with open(args.file, "w", encoding="utf-8") as f:
        f.write(args.version.strip() + "\n")
    return 0

def main(argv=None):
    p = argparse.ArgumentParser(prog="toolchain.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare", help="print current=, latest= and newer= lines")
    c.add_argument("file", help="version file, for example .java-version")
    c.add_argument("latest", help="newest available version")
    c.add_argument("--parts", type=int, default=1, help="numeric components that count (1 for a JDK, 2 for Python)")
    b = sub.add_parser("bump", help="write a version into a version file")
    b.add_argument("file")
    b.add_argument("version")
    args = p.parse_args(argv)
    try:
        return cmd_compare(args) if args.cmd == "compare" else cmd_bump(args)
    except (ValueError, OSError) as err:
        print("toolchain: %s" % err, file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
