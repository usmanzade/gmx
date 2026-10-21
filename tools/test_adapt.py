import copy
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapt

FIXTURE_TEXT = r'''{
  "schema": 1,
  "package": "ir.ilmili.telegraph",
  "device_tested": ["13.0.2.0"],
  "targets": [
    {
      "id": "launch",
      "role": "anchor",
      "params": ["android.os.Bundle"],
      "returns": "void",
      "variants": [
        {"class": "org.telegram.ui.LaunchActivity", "method": "onCreate", "versions": ["13.0.2.0"]}
      ]
    },
    {
      "id": "premium",
      "role": "constant",
      "group": "telegram",
      "value": true,
      "params": [],
      "returns": "boolean",
      "marker": "org.telegram.tgnet.TLRPC$User",
      "fingerprint": {
        "owner_field": "org.telegram.tgnet.TLRPC$User",
        "reads_field": ["org.telegram.tgnet.TLRPC$User", "premium"],
        "trusted_on": null
      },
      "variants": [
        {"class": "org.telegram.messenger.v40", "method": "w", "versions": ["13.0.2.0"]}
      ]
    },
    {
      "id": "expire",
      "role": "constant",
      "group": "telegraph",
      "native": true,
      "value": false,
      "params": ["long"],
      "returns": null,
      "variants": [
        {"class": "org.telegram.tgnet.ConnectionsManager", "method": "native_expireFile", "versions": ["13.0.2.0"]}
      ]
    },
    {
      "id": "days",
      "role": "constant",
      "group": "telegraph",
      "native": true,
      "value": 999,
      "params": ["long"],
      "returns": null,
      "variants": [
        {"class": "org.telegram.tgnet.ConnectionsManager", "method": "native_daysFile", "versions": ["13.0.2.0"]}
      ]
    },
    {
      "id": "license",
      "role": "constant",
      "group": "telegraph",
      "native": true,
      "value": true,
      "params": ["long"],
      "returns": null,
      "variants": [
        {"class": "org.telegram.tgnet.ConnectionsManager", "method": "native_checkLicense", "versions": ["13.0.2.0"]}
      ]
    },
    {
      "id": "remove",
      "role": "constant",
      "group": "telegraph",
      "native": true,
      "value": true,
      "params": ["int", "boolean"],
      "returns": null,
      "variants": [
        {"class": "org.telegram.tgnet.ConnectionsManager", "method": "native_removeInstance", "versions": ["13.0.2.0"]}
      ]
    }
  ]
}
'''

USER = "Lorg/telegram/tgnet/TLRPC$User;"
READ = ("iget-boolean", "v0, v0, Lorg/telegram/tgnet/TLRPC$User;->premium Z")

def method(name, desc, flags=1, ins=()):
    return adapt.Method(name, desc, flags, lambda: iter(ins))

def premium_class(name, mname, reads=True):
    return adapt.Klass(name, [("currentUser", USER)], [method(mname, "()Z", 1, [READ] if reads else [])])

def conn(natives=True):
    flags = 0x109 if natives else 1
    return adapt.Klass("org.telegram.tgnet.ConnectionsManager", [], [
        method("native_expireFile", "(J)Z", flags), method("native_daysFile", "(J)I", flags),
        method("native_checkLicense", "(J)Z", flags), method("native_removeInstance", "(IZ)V", flags)])

def launch():
    return adapt.Klass("org.telegram.ui.LaunchActivity", [], [method("onCreate", "(Landroid/os/Bundle;)V", 4)])

def index(*classes):
    return {c.name: c for c in classes}

def data(trusted=None):
    d = json.loads(FIXTURE_TEXT)
    if trusted:
        target(d, "premium")["fingerprint"]["trusted_on"] = trusted
    return d

def target(d, target_id):
    return next(t for t in d["targets"] if t["id"] == target_id)

def result(results, target_id):
    return next(r for r in results if r["id"] == target_id)

def current_build(*extra):
    return index(premium_class("org.telegram.messenger.v40", "w"), conn(), launch(), *extra)

class AnalyzeTests(unittest.TestCase):
    def test_same_names_only_record_version(self):
        d = data()
        res = adapt.analyze(d, current_build(), "13.1.0.0")
        self.assertTrue(all(r["status"] == "OK" for r in res))
        premium = target(d, "premium")
        self.assertEqual(len(premium["variants"]), 1)
        self.assertEqual(premium["variants"][0]["versions"], ["13.0.2.0", "13.1.0.0"])
        self.assertEqual(premium["fingerprint"]["trusted_on"], "13.1.0.0")
        self.assertEqual(adapt.render_java(d), adapt.render_java(data()))

    def test_rerun_on_recorded_build_changes_nothing(self):
        d = data(trusted="13.0.2.0")
        before = adapt.dump_json(d)
        res = adapt.analyze(d, current_build(), "13.0.2.0")
        self.assertTrue(all(r["status"] == "OK" for r in res))
        self.assertEqual(adapt.dump_json(d), before)

    def test_untrusted_fingerprint_never_relocates(self):
        d = data()
        res = adapt.analyze(d, index(premium_class("org.telegram.messenger.zz9", "q"), conn(), launch()), "13.1.0.0")
        self.assertEqual(result(res, "premium")["status"], "MISSING")
        self.assertIsNone(target(d, "premium")["fingerprint"]["trusted_on"])

    def test_trusted_fingerprint_relocates_once(self):
        d = data(trusted="13.0.2.0")
        moved = index(premium_class("org.telegram.messenger.zz9", "q"), conn(), launch())
        res = adapt.analyze(d, moved, "13.1.0.0")
        self.assertEqual(result(res, "premium")["status"], "MOVED")
        self.assertEqual([(v["class"], v["method"]) for v in target(d, "premium")["variants"]],
                         [("org.telegram.messenger.zz9", "q"), ("org.telegram.messenger.v40", "w")])
        self.assertIn('{"org.telegram.messenger.zz9", "q"}, {"org.telegram.messenger.v40", "w"}', adapt.render_java(d))
        res = adapt.analyze(d, moved, "13.1.1.0")
        self.assertEqual(result(res, "premium")["status"], "OK")
        self.assertEqual(len(target(d, "premium")["variants"]), 2)

    def test_ambiguous_and_suspect_change_nothing(self):
        d = data(trusted="13.0.2.0")
        two = index(premium_class("org.telegram.messenger.a1", "q"), premium_class("org.telegram.messenger.b2", "r"), conn(), launch())
        self.assertEqual(result(adapt.analyze(d, two, "13.1.0.0"), "premium")["status"], "AMBIGUOUS")
        sus = index(premium_class("org.telegram.messenger.v40", "w", reads=False),
                    premium_class("org.telegram.messenger.b2", "r"), conn(), launch())
        self.assertEqual(result(adapt.analyze(d, sus, "13.1.0.0"), "premium")["status"], "SUSPECT")
        self.assertEqual(len(target(d, "premium")["variants"]), 1)

    def test_unsafe_candidate_name_is_refused(self):
        d = data(trusted="13.0.2.0")
        evil = premium_class("org.telegram.messenger.a1", 'q"; evil();//')
        res = adapt.analyze(d, index(evil, conn(), launch()), "13.1.0.0")
        self.assertEqual(result(res, "premium")["status"], "MISSING")
        self.assertNotIn("evil", adapt.render_java(d))

    def test_native_checks(self):
        res = adapt.analyze(data(), current_build_without_natives(), "x.1")
        self.assertEqual(result(res, "expire")["status"], "MISSING")
        self.assertEqual(result(res, "launch")["status"], "OK")

    def test_marker_must_exist(self):
        no_marker = adapt.Klass("org.telegram.messenger.v40", [], [method("w", "()Z", 1)])
        res = adapt.analyze(data(), index(no_marker, conn(), launch()), "x.1")
        self.assertEqual(result(res, "premium")["status"], "MISSING")

def current_build_without_natives():
    return index(premium_class("org.telegram.messenger.v40", "w"), conn(natives=False), launch())

class GeneratedFileTests(unittest.TestCase):
    def test_json_layout_is_stable(self):
        self.assertEqual(adapt.dump_json(json.loads(FIXTURE_TEXT)), FIXTURE_TEXT)

    def test_group_defaults_for_older_files(self):
        self.assertEqual(adapt.group_of({"native": True}), "telegraph")
        self.assertEqual(adapt.group_of({}), "telegram")
        self.assertEqual(adapt.group_of({"group": "x", "native": True}), "x")

    def test_java_contains_groups(self):
        java = adapt.render_java(data())
        self.assertIn('new Target("premium", "telegram", Boolean.TRUE, false,', java)
        self.assertIn('new Target("remove", "telegraph", Boolean.TRUE, true,', java)
        self.assertIn('new Target("launch", null, null, false,', java)

    def test_repository_files_are_in_sync(self):
        d = adapt.load_data()
        self.assertEqual(adapt.read_text(adapt.JAVA_OUT), adapt.render_java(d))
        self.assertEqual(adapt.read_text(adapt.SUPPORTED_MD), adapt.render_supported(d))
        self.assertEqual(adapt.read_text(adapt.TARGETS_JSON), adapt.dump_json(d))
        for t in d["targets"]:
            self.assertTrue(t["variants"], t["id"])
            self.assertTrue(all(v["versions"] for v in t["variants"]), t["id"])

    def test_bump_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gradle.properties")
            with open(path, "w") as f:
                f.write("a=1\nGMX_VERSION_NAME=1.0.0\nGMX_VERSION_CODE=100\n")
            old, adapt.PROPS = adapt.PROPS, path
            try:
                self.assertEqual(adapt.bump_version(), "1.0.1")
                self.assertEqual(adapt.bump_version(), "1.0.2")
            finally:
                adapt.PROPS = old
            self.assertEqual(adapt.read_text(path), "a=1\nGMX_VERSION_NAME=1.0.2\nGMX_VERSION_CODE=102\n")

class JsonErrorTests(unittest.TestCase):

    def explain(self, text):
        try:
            json.loads(text)
        except json.JSONDecodeError as err:
            return adapt.describe_json_error(text, err)
        self.fail("text is valid JSON")

    def test_trailing_comma_in_object(self):
        msg = self.explain('{\n  "a": 1,\n}\n')
        self.assertIn("trailing comma at line 2, column 9", msg)
        self.assertIn('  2 |   "a": 1,', msg)

    def test_trailing_comma_in_array(self):
        self.assertIn("trailing comma at line 1, column 9", self.explain('{"a": [1,]}'))

    def test_comma_inside_a_string_is_not_a_trailing_comma(self):
        msg = self.explain('{"a": "x,}"')
        self.assertIn("not valid JSON", msg)
        self.assertNotIn("trailing comma", msg)

    def test_other_errors_keep_line_and_column(self):
        msg = self.explain('{\n  "a": ,\n}\n')
        self.assertIn("not valid JSON", msg)
        self.assertIn("line 2", msg)

    def test_conflict_marker(self):
        msg = self.explain('{\n  "a": 1,\n<<<<<<< HEAD\n  "b": 2\n}\n')
        self.assertIn("merge-conflict marker at line 3", msg)

    def test_load_data_reports_instead_of_tracing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "targets.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"a": 1,}')
            old, adapt.TARGETS_JSON = adapt.TARGETS_JSON, path
            try:
                with self.assertRaises(SystemExit) as ctx:
                    adapt.load_data()
            finally:
                adapt.TARGETS_JSON = old
        self.assertIn("not valid JSON", str(ctx.exception))

class FileTests(unittest.TestCase):
    def test_find_base_apk_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, entries in (("a.apks", ["base.apk", "split_config.arm64.apk"]),
                                  ("b.apks", ["splits/base-master.apk", "splits/base-xxhdpi.apk"]),
                                  ("c.apkm", ["info.json", "only.apk"])):
                path = os.path.join(tmp, name)
                with zipfile.ZipFile(path, "w") as z:
                    for e in entries:
                        z.writestr(e, "x")
                out = adapt.find_base_apk(path, os.path.join(tmp, "o"))
                self.assertTrue(os.path.exists(out), name)

    def test_version_order(self):
        self.assertEqual(sorted(["13.0.10.0", "13.0.2.0", "13.0.9.1"], key=adapt.vkey),
                         ["13.0.2.0", "13.0.9.1", "13.0.10.0"])

if __name__ == "__main__":
    unittest.main()
