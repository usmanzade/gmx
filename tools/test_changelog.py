import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog

def data(versions, tested=("13.0.2.0",)):
    return {
        "device_tested": list(tested),
        "targets": [{"id": "premium", "variants": [{"class": "a.B", "method": "c", "versions": list(versions)}]}],
    }

ONE = data(["13.0.2.0"])
TWO = data(["13.0.2.0", "13.1.0.0"])
MODULE = ["app/src/main/java/com/usmanzade/gmx/GmxModule.java"]

class RenderTests(unittest.TestCase):
    def test_first_release(self):
        self.assertEqual(changelog.render(ONE, changelog.EMPTY, [], first=True),
                         "- Initial release. Supports Graph Messenger 13.0.2.0.\n")

    def test_first_release_marks_untested_builds(self):
        text = changelog.render(data(["13.0.2.0", "13.1.0.0"]), changelog.EMPTY, [], first=True)
        self.assertIn("13.1.0.0 (not device-tested)", text)
        self.assertNotIn("13.0.2.0 (", text)

    def test_new_build_only_what_is_new(self):
        text = changelog.render(TWO, ONE, [("Adapt to Graph Messenger 13.1.0.0", ["targets.json", "SUPPORTED.md"])])
        self.assertEqual(text, "- Added support for Graph Messenger 13.1.0.0 (not device-tested).\n")

    def test_tested_build_has_no_suffix(self):
        text = changelog.render(data(["13.0.2.0", "13.1.0.0"], tested=("13.0.2.0", "13.1.0.0")), ONE, [])
        self.assertEqual(text, "- Added support for Graph Messenger 13.1.0.0.\n")

    def test_module_commits_are_listed_once(self):
        subjects = [("Fix log wording", MODULE), ("Fix log wording", MODULE), ("Update CI", [".github/workflows/ci.yml"]),
                    ("Update README", ["README.md"])]
        self.assertEqual(changelog.render(ONE, ONE, subjects), "- Fix log wording\n")

    def test_generated_files_alone_are_not_a_module_change(self):
        files = ["app/src/main/java/com/usmanzade/gmx/Targets.java", "targets.json"]
        self.assertEqual(changelog.render(ONE, ONE, [("Adapt", files)]), "- No user-facing changes.\n")

    def test_unreadable_targets_still_produce_notes(self):
        self.assertEqual(changelog.render(None, None, [("Fix log wording", MODULE)]), "- Fix log wording\n")
        self.assertEqual(changelog.render(None, None, [], first=True), "- Initial release.\n")

class RepositoryTests(unittest.TestCase):
    def repo(self, tmp, first_text, second_text, second_files=None):
        def git(*args):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=tmp, check=True,
                           capture_output=True)

        def save(name, text):
            path = os.path.join(tmp, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

        git("init", "-q")
        save("targets.json", first_text)
        git("add", ".")
        git("commit", "-qm", "Initial")
        git("tag", "v1.0.0")
        save("targets.json", second_text)
        for name, text in (second_files or {}).items():
            save(name, text)
        git("add", ".")
        git("commit", "-qm", "Second")
        git("tag", "v1.0.1")

    def run_tool(self, tmp, tag="v1.0.1"):
        return subprocess.run([sys.executable, changelog.__file__, "--tag", tag, "--ref", tag, "--repo-dir", tmp],
                              capture_output=True, text=True, encoding="utf-8")

    def test_previous_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, json.dumps(ONE), json.dumps(TWO))
            self.assertEqual(changelog.previous_tag("v1.0.1", tmp), "v1.0.0")
            self.assertIsNone(changelog.previous_tag("v1.0.0", tmp))
            self.assertEqual(changelog.previous_tag("v1.0.10", tmp), "v1.0.1")

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, json.dumps(ONE), json.dumps(TWO))
            out = self.run_tool(tmp)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout, "- Added support for Graph Messenger 13.1.0.0 (not device-tested).\n")

    def test_first_tag_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, json.dumps(ONE), json.dumps(TWO))
            out = self.run_tool(tmp, "v1.0.0")
        self.assertEqual(out.stdout, "- Initial release. Supports Graph Messenger 13.0.2.0.\n")

    def test_trailing_comma_does_not_stop_the_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, json.dumps(ONE), '{\n  "targets": [],\n}\n',
                      {"app/src/main/java/com/usmanzade/gmx/GmxModule.java": "class A {}"})
            out = self.run_tool(tmp)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout, "- Second\n")
        self.assertIn("trailing comma at line 2", out.stderr)

    def test_conflict_markers_are_named(self):
        broken = '{\n  "targets": [],\n<<<<<<< HEAD\n  "device_tested": []\n=======\n  "device_tested": ["1"]\n>>>>>>> x\n}\n'
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, json.dumps(ONE), broken)
            out = self.run_tool(tmp)
        self.assertEqual(out.returncode, 0)
        self.assertIn("merge-conflict marker at line 3", out.stderr)

    def test_unreadable_previous_release_only_drops_the_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, '{"targets": [,]}', json.dumps(TWO))
            out = self.run_tool(tmp)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout, "- No user-facing changes.\n")
        self.assertIn("v1.0.0: ", out.stderr)

    def test_missing_targets_file_in_older_release_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp, "", json.dumps(TWO))
            os.remove(os.path.join(tmp, "targets.json"))
            out = self.run_tool(tmp)
        self.assertEqual(out.returncode, 0)

if __name__ == "__main__":
    unittest.main()
