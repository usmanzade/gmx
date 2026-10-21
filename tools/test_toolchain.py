import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain

class CompareTests(unittest.TestCase):
    def test_jdk_major_only(self):
        self.assertTrue(toolchain.compare("25", "27", 1))
        self.assertFalse(toolchain.compare("27", "27", 1))
        self.assertFalse(toolchain.compare("27", "25", 1))
        self.assertFalse(toolchain.compare("25.0.1", "25", 1))
        self.assertTrue(toolchain.compare("25.0.1", "26.0.0+8", 1))

    def test_python_major_minor(self):
        self.assertTrue(toolchain.compare("3.14", "3.15", 2))
        self.assertFalse(toolchain.compare("3.15", "3.15.0", 2))
        self.assertFalse(toolchain.compare("3.14.2", "3.14.9", 2))
        self.assertTrue(toolchain.compare("3.9", "3.10", 2))

    def test_unreadable_version(self):
        with self.assertRaises(ValueError):
            toolchain.parse("latest", 1)
        with self.assertRaises(ValueError):
            toolchain.parse("3", 2)

class CommandTests(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = toolchain.main(list(argv))
        return code, out.getvalue()

    def test_compare_output_is_github_output_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".java-version")
            with open(path, "w") as f:
                f.write("25\n")
            code, out = self.run_main("compare", path, "27")
            self.assertEqual(code, 0)
            self.assertEqual(out.split(), ["current=25", "latest=27", "newer=true"])
            code, out = self.run_main("compare", path, "25")
            self.assertIn("newer=false", out)

    def test_bump_rewrites_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".python-version")
            with open(path, "w") as f:
                f.write("3.14\n")
            self.assertEqual(self.run_main("bump", path, "3.15")[0], 0)
            with open(path) as f:
                self.assertEqual(f.read(), "3.15\n")

    def test_bad_input_fails_without_touching_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v")
            with open(path, "w") as f:
                f.write("25\n")
            self.assertEqual(self.run_main("bump", path, "latest")[0], 1)
            with open(path) as f:
                self.assertEqual(f.read(), "25\n")
            self.assertEqual(self.run_main("compare", os.path.join(tmp, "missing"), "27")[0], 1)

if __name__ == "__main__":
    unittest.main()
