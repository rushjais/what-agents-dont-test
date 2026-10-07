"""Tests for the reference packignore.

Two jobs:
  1. The reference does what V2_DESIGN.md says.
  2. Fairness: every hidden rule changes the answer on a SMALL input (<= 3
     lines, a handful of files), so an agent running careful experiments can
     find it. Each hidden-rule test asserts that switching the rule off gives
     a different answer on that small input.

    python3 -m unittest v2/reference/test_packignore.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from packignore import ABLATIONS, README_ONLY, TRUE, ignored_files  # noqa: E402


def run(files, rules=TRUE):
    with tempfile.TemporaryDirectory() as root:
        for rel, content in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("x\n" if content is None else content)
        return ignored_files(root, rules)


class Documented(unittest.TestCase):
    def test_d1_blank_lines(self):
        self.assertEqual(run({".packignore": "\n*.log\n\n", "a.log": None, "b.txt": None}), ["a.log"])

    def test_d2_star_question_doublestar(self):
        self.assertEqual(run({".packignore": "?.t*\n", "a.txt": None, "ab.txt": None}), ["a.txt"])
        self.assertEqual(run({".packignore": "a/**/x\n", "a/x": None, "a/b/x": None, "b/x": None}),
                         ["a/b/x", "a/x"])

    def test_d3_unanchored_vs_anchored(self):
        self.assertEqual(run({".packignore": "x\n", "x": None, "d/x": None}), ["d/x", "x"])
        self.assertEqual(run({".packignore": "/x\n", "x": None, "d/x": None}), ["x"])
        self.assertEqual(run({"d/.packignore": "e/x\n", "d/e/x": None, "e/x": None}), ["d/e/x"])

    def test_d4_negation(self):
        self.assertEqual(run({".packignore": "*.log\n!keep.log\n", "a.log": None, "keep.log": None}),
                         ["a.log"])

    def test_d5_nested_files(self):
        self.assertEqual(run({"d/.packignore": "*.tmp\n", "d/a.tmp": None, "a.tmp": None}), ["d/a.tmp"])

    def test_directory_pattern(self):
        self.assertEqual(run({".packignore": "build/\n", "build/a": None, "src/build": None}),
                         ["build/a"])


class Hidden(unittest.TestCase):
    """Each test: small input, true answer, and proof the rule matters on it."""

    def assert_rule(self, name, files, expected):
        self.assertEqual(run(files), expected)
        self.assertNotEqual(run(files, ABLATIONS[name]), expected,
                            f"{name} doesn't change the answer on this input")

    def test_w1_semicolon_comments_hash_is_a_pattern(self):
        self.assert_rule("W1_semicolon_comments",
                         {".packignore": "; logs\n#notes\n", "#notes": None, "; logs": None},
                         ["#notes"])

    def test_h1_most_specific_wins(self):
        # gitignore-style last-match-wins would ignore keep.log
        self.assert_rule("H1_specificity",
                         {".packignore": "!keep.log\n*.log\n", "keep.log": None, "a.log": None},
                         ["a.log"])

    def test_h2_doublestar_depth_limit(self):
        self.assert_rule("H2_depth_limit",
                         {".packignore": "**/x\n", "a/x": None, "a/b/c/x": None, "a/b/c/d/x": None},
                         ["a/b/c/x", "a/x"])

    def test_h3_reinclude_inside_excluded_dir(self):
        self.assert_rule("H3_reinclude",
                         {".packignore": "build/\n!build/keep\n", "build/keep": None, "build/a": None},
                         ["build/a"])

    def test_h3_packignore_in_excluded_dir_not_read(self):
        self.assertEqual(run({".packignore": "d/\n!d/*\n", "d/.packignore": "a\n", "d/a": None}), [])

    def test_h4_braces(self):
        self.assert_rule("H4_braces",
                         {".packignore": "*.{log,tmp}\n", "a.log": None, "b.tmp": None, "c.txt": None},
                         ["a.log", "b.tmp"])


class Baseline(unittest.TestCase):
    def test_readme_only_differs_from_truth_on_each_hidden_example(self):
        files = {".packignore": "!keep.log\n*.log\n", "keep.log": None}
        self.assertNotEqual(run(files), run(files, README_ONLY))


if __name__ == "__main__":
    unittest.main()
