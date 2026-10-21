import argparse
import json
import os
import re
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS_JSON = os.path.join(ROOT, "targets.json")
JAVA_OUT = os.path.join(ROOT, "app/src/main/java/com/usmanzade/gmx/Targets.java")
SUPPORTED_MD = os.path.join(ROOT, "SUPPORTED.md")
PROPS = os.path.join(ROOT, "gradle.properties")

ACC_STATIC, ACC_NATIVE, ACC_ABSTRACT = 0x8, 0x100, 0x400
PRIM = {"void": "V", "boolean": "Z", "int": "I", "long": "J", "byte": "B",
        "short": "S", "char": "C", "float": "F", "double": "D"}
PROBLEMS = {"SUSPECT", "AMBIGUOUS", "MISSING"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.$]+$")
SAFE_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

def to_desc(java_type):
    dims = 0
    while java_type.endswith("[]"):
        dims += 1
        java_type = java_type[:-2]
    base = PRIM.get(java_type) or "L" + java_type.replace(".", "/") + ";"
    return "[" * dims + base

def param_desc(params):
    return "(" + "".join(to_desc(p) for p in params) + ")"

def java_name(class_desc):
    return class_desc[1:-1].replace("/", ".")

class Method:
    __slots__ = ("name", "desc", "flags", "ins")

    def __init__(self, name, desc, flags, ins):
        self.name, self.desc, self.flags, self.ins = name, desc, flags, ins

class Klass:
    __slots__ = ("name", "fields", "methods")

    def __init__(self, name, fields, methods):
        self.name, self.fields, self.methods = name, fields, methods

def load_index(apk_path, wanted_classes, owner_descs):
    from loguru import logger
    logger.remove()
    from androguard.core.dex import DEX

    index = {}
    with zipfile.ZipFile(apk_path) as z:
        dex_names = sorted(n for n in z.namelist() if re.fullmatch(r"classes\d*\.dex", n))
        if not dex_names:
            raise SystemExit("no classes*.dex in " + apk_path)
        for n in dex_names:
            dex = DEX(z.read(n))
            for c in dex.get_classes():
                name = java_name(c.get_name())
                fields = [(f.get_name(), f.get_descriptor()) for f in c.get_fields()]
                if name not in wanted_classes and not any(d in owner_descs for _, d in fields):
                    continue
                methods = []
                for m in c.get_methods():
                    def ins(m=m):
                        return ((i.get_name(), i.get_output()) for i in m.get_instructions()) \
                            if m.get_code() else iter(())
                    methods.append(Method(m.get_name(), m.get_descriptor().replace(" ", ""),
                                          m.get_access_flags(), ins))
                index[name] = Klass(name, fields, methods)
            print("scanned", n, file=sys.stderr, flush=True)
    return index

def wanted_from(data):
    classes, owners = set(), set()
    for t in data["targets"]:
        classes.update(v["class"] for v in t["variants"])
        if t.get("fingerprint"):
            owners.add(to_desc(t["fingerprint"]["owner_field"]))
    return classes, owners

def variant_matches(index, target, variant):
    klass = index.get(variant["class"])
    if klass is None:
        return False
    prefix = param_desc(target["params"])
    ret = None if target.get("returns") is None else to_desc(target["returns"])
    for m in klass.methods:
        if m.name != variant["method"] or not m.desc.startswith(prefix):
            continue
        if ret is not None and m.desc[len(prefix):] != ret:
            continue
        if target.get("native") and not m.flags & ACC_NATIVE:
            continue
        marker = target.get("marker")
        if marker and not any(d == to_desc(marker) for _, d in klass.fields):
            continue
        return True
    return False

def fingerprint_candidates(index, target):
    fp = target["fingerprint"]
    owner = to_desc(fp["owner_field"])
    needle = "%s->%s " % (to_desc(fp["reads_field"][0]), fp["reads_field"][1])
    want = param_desc(target["params"]) + to_desc(target["returns"])
    found = []
    for klass in index.values():
        if not any(d == owner for _, d in klass.fields):
            continue
        for m in klass.methods:
            if m.desc != want or m.flags & (ACC_STATIC | ACC_NATIVE | ACC_ABSTRACT):
                continue
            if any(op.startswith("iget") and needle in out for op, out in m.ins()):
                found.append((klass.name, m.name))
    return sorted(found)

def vkey(version):
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"[.\-]", version)]

def add_version(variant, version):
    if version not in variant["versions"]:
        variant["versions"] = sorted(variant["versions"] + [version], key=vkey)
        return True
    return False

def fmt(cands):
    return ", ".join("%s#%s" % c for c in cands) or "none"

def analyze(data, index, version):
    results = []
    for t in data["targets"]:
        res = {"id": t["id"], "status": "OK", "detail": "", "notes": []}
        results.append(res)
        matched = [v for v in t["variants"] if variant_matches(index, t, v)]
        fp = t.get("fingerprint")
        cands = fingerprint_candidates(index, t) if fp else []
        trusted = bool(fp and fp.get("trusted_on"))

        if matched:
            first = matched[0]
            res["detail"] = "%s#%s" % (first["class"], first["method"])
            if fp:
                names = {(v["class"], v["method"]) for v in matched}
                hit = [c for c in cands if c in names]
                if hit and len(cands) == 1:
                    if not trusted:
                        fp["trusted_on"] = version
                        res["notes"].append("fingerprint confirmed the known target on %s: relocation enabled" % version)
                elif hit:
                    res["notes"].append("fingerprint found %d candidates (%s); not enough to trust it" % (len(cands), fmt(cands)))
                elif trusted:
                    res["status"] = "SUSPECT"
                    res["detail"] += " matches by signature, but the fingerprint finds: " + fmt(cands)
                    continue
                else:
                    res["notes"].append("fingerprint does not describe the known target (finds: %s); relocation stays disabled" % fmt(cands))
            add_version(first, version)
            continue

        if trusted and len(cands) == 1 and not all(SAFE_NAME.match(x) for x in cands[0]):
            res["status"], res["detail"] = "MISSING", "candidate has unexpected characters in its name"
        elif trusted and len(cands) == 1:
            cls, method = cands[0]
            same = [v for v in t["variants"] if (v["class"], v["method"]) == (cls, method)]
            if same:
                add_version(same[0], version)
                res["notes"].append("existing variant revived after a signature mismatch")
            else:
                t["variants"].insert(0, {"class": cls, "method": method, "versions": [version], "auto": True})
            res["status"], res["detail"] = "MOVED", "%s#%s" % (cls, method)
        elif trusted and len(cands) > 1:
            res["status"], res["detail"] = "AMBIGUOUS", "candidates: " + fmt(cands)
        else:
            res["status"] = "MISSING"
            res["detail"] = "no variant matches" + ("; fingerprint candidates: " + fmt(cands) if fp else "")
            if fp and not trusted:
                res["notes"].append("fingerprint is not trusted yet, so no relocation was attempted")
    return results

def const_name(target_id):
    return re.sub(r"[^A-Za-z0-9]", "_", target_id).upper()

def jstr(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')

def jvalue(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "Boolean.TRUE" if v else "Boolean.FALSE"
    return "Integer.valueOf(%d)" % v

def render_java(data):
    lines = [
        "package com.usmanzade.gmx;",
        "",
        "final class Targets {",
        "    private Targets() {}",
        "",
    ]
    constants, anchor = [], None
    for t in data["targets"]:
        name = const_name(t["id"])
        params = "new String[] {%s}" % ", ".join(jstr(p) for p in t["params"])
        variants = "new String[][] {%s}" % ", ".join(
            "{%s, %s}" % (jstr(v["class"]), jstr(v["method"])) for v in t["variants"])
        group = jstr(group_of(t)) if t["role"] != "anchor" else "null"
        lines.append("    static final Target %s = new Target(%s, %s, %s, %s, %s, %s, %s,\n            %s);" % (
            name, jstr(t["id"]), group, jvalue(t.get("value")), "true" if t.get("native") else "false",
            params, jstr(t["returns"]) if t.get("returns") else "null",
            jstr(t["marker"]) if t.get("marker") else "null", variants))
        if t["role"] == "anchor":
            anchor = name
        else:
            constants.append(name)
    lines += ["",
              "    static final Target[] CONSTANTS = {%s};" % ", ".join(constants),
              "",
              "    static final Target ANCHOR = %s;" % (anchor or "null"), "}", ""]
    return "\n".join(lines)

def render_supported(data):
    versions = sorted({v for t in data["targets"] for var in t["variants"] for v in var["versions"]},
                      key=vkey, reverse=True)
    tested = set(data.get("device_tested", []))
    head = ["Graph build"] + [t["id"] for t in data["targets"]] + ["device-tested"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for ver in versions:
        cells = []
        for t in data["targets"]:
            var = next((v for v in t["variants"] if ver in v["versions"]), None)
            cells.append("`%s#%s`" % (var["class"].rsplit(".", 1)[-1], var["method"]) if var else "-")
        rows.append("| %s | %s | %s |" % (ver, " | ".join(cells), "yes" if ver in tested else "static only"))
    return "# Supported Graph Messenger builds\n\n" + "\n".join(rows) + "\n"

def write_if_changed(path, text):
    if os.path.exists(path) and read_text(path) == text:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True

def bump_version():
    text = read_text(PROPS)
    name = re.search(r"^GMX_VERSION_NAME=(.+)$", text, re.M).group(1).strip()
    code = int(re.search(r"^GMX_VERSION_CODE=(\d+)$", text, re.M).group(1))
    parts = name.split(".")
    while len(parts) < 3:
        parts.append("0")
    parts[2] = str(int(parts[2]) + 1)
    new_name = ".".join(parts)
    text = re.sub(r"^GMX_VERSION_NAME=.+$", "GMX_VERSION_NAME=" + new_name, text, flags=re.M)
    text = re.sub(r"^GMX_VERSION_CODE=\d+$", "GMX_VERSION_CODE=%d" % (code + 1), text, flags=re.M)
    with open(PROPS, "w", encoding="utf-8") as f:
        f.write(text)
    return new_name

def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

def group_of(target):
    return target.get("group") or ("telegraph" if target.get("native") else "telegram")

def _scalar(v):
    return json.dumps(v, ensure_ascii=False)

def _inline(v):
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (_scalar(k), _inline(x)) for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_inline(x) for x in v) + "]"
    return _scalar(v)

def _flat(d):
    return all(not isinstance(x, dict) and
               (not isinstance(x, list) or all(not isinstance(y, (dict, list)) for y in x))
               for x in d.values())

def _dump(v, depth):
    pad = "  " * depth
    if isinstance(v, dict):
        items = ["%s  %s: %s" % (pad, _scalar(k), _dump(x, depth + 1)) for k, x in v.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(v, list):
        if all(not isinstance(x, (dict, list)) for x in v):
            return _inline(v)
        items = [pad + "  " + (_inline(x) if isinstance(x, dict) and _flat(x) else _dump(x, depth + 1))
                 for x in v]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return _scalar(v)

def dump_json(data):
    return _dump(data, 0) + "\n"

CONFLICT_MARKER = re.compile(r"^(<{7}|={7}|>{7})(\s|$)")

def find_trailing_comma(text):
    in_string = escaped = False
    comma = None
    line, col = 1, 0
    for ch in text:
        col += 1
        if ch == "\n":
            line, col = line + 1, 0
            continue
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string, comma = True, None
        elif ch == ",":
            comma = (line, col)
        elif ch in "}]":
            if comma:
                return comma
        elif not ch.isspace():
            comma = None
    return None

def _excerpt(lines, first, last):
    return ["  %d | %s" % (n, lines[n - 1][:100]) for n in range(max(1, first), min(len(lines), last) + 1)]

def describe_json_error(text, err, name="targets.json"):
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        if CONFLICT_MARKER.match(line):
            return ("%s contains a merge-conflict marker at line %d (%s). Resolve the conflict, remove the "
                    "<<<<<<<, ======= and >>>>>>> lines, and commit again." % (name, number, line.strip()[:40]))
    comma = find_trailing_comma(text)
    if comma:
        out = ["%s is not valid JSON: trailing comma at line %d, column %d (a comma right before a closing "
               "brace or bracket). Remove it." % (name, comma[0], comma[1])]
        return "\n".join(out + _excerpt(lines, comma[0] - 1, comma[0] + 1))
    out = ["%s is not valid JSON: %s at line %d, column %d." % (name, err.msg, err.lineno, err.colno)]
    return "\n".join(out + _excerpt(lines, err.lineno - 1, err.lineno))

def load_data():
    text = read_text(TARGETS_JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise SystemExit(describe_json_error(text, err))

def save_data(data):
    write_if_changed(TARGETS_JSON, dump_json(data))

def find_base_apk(path, tmp):
    if path.lower().endswith(".apk"):
        return path
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        apks = [n for n in names if n.lower().endswith(".apk")]
        pick = next((n for n in ("base.apk", "splits/base-master.apk", "base-master.apk") if n in names), None)
        if pick is None:
            pick = next((n for n in apks if os.path.basename(n).startswith("base")), None)
        if pick is None and len(apks) == 1:
            pick = apks[0]
        if pick is None:
            raise SystemExit("no base.apk in %s (found: %s)" % (path, ", ".join(apks) or "no apks"))
        return z.extract(pick, tmp)

def apk_version(apk_path):
    from loguru import logger
    logger.remove()
    from androguard.core.apk import APK
    return APK(apk_path).get_androidversion_name()

def render_report(version, results, applied, new_version, record_changed):
    out = ["## Graph Messenger %s" % version, ""]
    for r in results:
        out.append("- **%s** `%s`: %s" % (r["status"], r["id"], r["detail"]))
        out.extend("  - %s" % n for n in r["notes"])
    out.append("")
    if any(r["status"] in PROBLEMS for r in results):
        out.append("**Needs a human:** the targets marked SUSPECT, AMBIGUOUS or MISSING were not changed.")
    if any(r["status"] == "MOVED" for r in results):
        out.append("Moved targets were relocated by fingerprint (static match only). Test on a device before release.")
    if new_version:
        out.append("Module version bumped to %s." % new_version)
    elif applied and record_changed:
        out.append("Hook targets unchanged; only the supported-build record was updated (no release needed).")
    elif applied and not any(r["status"] in PROBLEMS for r in results):
        out.append("Nothing to update: this build is already recorded and every target matches.")
    return "\n".join(out) + "\n"

def cmd_analyze(args):
    data = load_data()
    with tempfile.TemporaryDirectory() as tmp:
        apk = find_base_apk(args.file, tmp)
        version = args.version or apk_version(apk)
        if not version or not SAFE_VERSION.match(version):
            raise SystemExit("unusable versionName %r; pass --version" % version)
        classes, owners = wanted_from(data)
        before = dump_json(data)
        results = analyze(data, load_index(apk, classes, owners), version)
        record_changed = dump_json(data) != before

    new_version = None
    if args.apply:
        save_data(data)
        java_changed = write_if_changed(JAVA_OUT, render_java(data))
        write_if_changed(SUPPORTED_MD, render_supported(data))
        if java_changed:
            new_version = bump_version()
    report = render_report(version, results, args.apply, new_version, record_changed)
    print(report)
    if args.report:
        with open(args.report, "w") as f:
            f.write(report)
    return 2 if any(r["status"] in PROBLEMS for r in results) else 0

def cmd_gen(args):
    data = load_data()
    java, md = render_java(data), render_supported(data)
    if args.check:
        stale = [p for p, t in ((JAVA_OUT, java), (SUPPORTED_MD, md))
                 if not os.path.exists(p) or read_text(p) != t]
        if stale:
            print("out of date (run: python3 tools/adapt.py gen): " + ", ".join(os.path.relpath(p, ROOT) for p in stale))
            return 1
        return 0
    write_if_changed(JAVA_OUT, java)
    write_if_changed(SUPPORTED_MD, md)
    return 0

def main(argv=None):
    p = argparse.ArgumentParser(prog="adapt.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="check a Graph Messenger build against targets.json")
    a.add_argument("file", help=".apks, .apkm or .apk file")
    a.add_argument("--apply", action="store_true", help="record the build, relocate moved targets, regenerate files")
    a.add_argument("--report", help="write the report to this file")
    a.add_argument("--version", help="override the versionName read from the APK")
    g = sub.add_parser("gen", help="regenerate Targets.java and SUPPORTED.md from targets.json")
    g.add_argument("--check", action="store_true", help="only verify that the generated files are current")
    args = p.parse_args(argv)
    return cmd_analyze(args) if args.cmd == "analyze" else cmd_gen(args)

if __name__ == "__main__":
    sys.exit(main())
