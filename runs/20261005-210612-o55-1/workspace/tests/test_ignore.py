import os
import tempfile
import unittest

from snapshot.ignore import ignored_files


def make_tree(root, files):
    """files maps relative path -> content (None means a dummy file)."""
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("x\n" if content is None else content)


class IgnoredFilesTest(unittest.TestCase):
    def check(self, files, expected):
        with tempfile.TemporaryDirectory() as root:
            make_tree(root, files)
            self.assertEqual(ignored_files(root), sorted(expected))

    def test_no_gitignore(self):
        self.check({"a.txt": None, "src/main.py": None}, [])

    def test_extension_glob_matches_at_any_depth(self):
        self.check({".gitignore": "*.log\n", "debug.log": None, "src/err.log": None,
                    "src/main.py": None},
                   ["debug.log", "src/err.log"])

    def test_directory_pattern_ignores_contents(self):
        self.check({".gitignore": "build/\n", "build/out.o": None, "build/sub/x.o": None,
                    "src/main.c": None},
                   ["build/out.o", "build/sub/x.o"])

    def test_trailing_slash_does_not_match_files(self):
        self.check({".gitignore": "build/\n", "build": None, "src/build/x": None},
                   ["src/build/x"])

    def test_negation(self):
        self.check({".gitignore": "*.log\n!keep.log\n", "a.log": None, "keep.log": None},
                   ["a.log"])

    def test_comments_and_blank_lines(self):
        self.check({".gitignore": "# logs\n\n*.log\n", "a.log": None, "b.txt": None},
                   ["a.log"])

    def test_leading_slash_anchors_to_gitignore_dir(self):
        self.check({".gitignore": "/todo.txt\n", "todo.txt": None, "docs/todo.txt": None},
                   ["todo.txt"])

    def test_nested_gitignore_is_relative_to_its_directory(self):
        self.check({"src/.gitignore": "/gen\n", "src/gen/a.py": None, "gen/b.py": None},
                   ["src/gen/a.py"])

    def test_gitignore_files_are_ordinary_files(self):
        self.check({".gitignore": "*\n!.gitignore\n", "a.txt": None},
                   ["a.txt"])

    def test_negation_cannot_reinclude_file_in_ignored_directory(self):
        self.check({".gitignore": "build/\n!build/keep\n", "build/keep": None, "build/x": None},
                   ["build/keep", "build/x"])

    def test_double_star_after_literal_prefix(self):
        # git matches the literal prefix "a" first, so the rest ("**/b") is
        # treated as a leading "**/" that can cross directories.
        self.check({".gitignore": "a**/b\n", "ax/y/b": None, "a/b": None, "ab": None, "c/b": None},
                   ["a/b", "ab", "ax/y/b"])

    def test_space_class_uses_gits_ctype(self):
        self.check({".gitignore": "[[:space:]]\n", "\x0b": None, "\t": None},
                   ["\t"])

    def test_trailing_spaces_and_escapes(self):
        self.check({".gitignore": "foo  \nbar\\ \n\\#a\n\\!b\n#c\n", "foo": None, "bar ": None,
                    "#a": None, "!b": None, "#c": None},
                   ["!b", "#a", "bar ", "foo"])

    def test_nested_git_dirs_are_skipped(self):
        self.check({".gitignore": "x\n", "sub/.git/x": None, "sub/x": None},
                   ["sub/x"])

    def test_paths_are_relative_and_use_forward_slashes(self):
        with tempfile.TemporaryDirectory() as root:
            make_tree(root, {".gitignore": "*.o\n", "a/b/c.o": None})
            self.assertEqual(ignored_files(root), ["a/b/c.o"])


if __name__ == "__main__":
    unittest.main()
