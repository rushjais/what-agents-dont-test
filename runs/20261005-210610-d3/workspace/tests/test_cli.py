import os
import tempfile
import unittest

from snapshot.cli import snapshot
from tests.test_ignore import make_tree


class SnapshotTest(unittest.TestCase):
    def test_copies_only_files_that_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tmp:
            make_tree(src, {".gitignore": "*.log\nbuild/\n", "main.py": None,
                            "debug.log": None, "build/out.o": None, "lib/util.py": None})
            dest = os.path.join(tmp, "out")
            n = snapshot(src, dest)
            copied = sorted(
                os.path.relpath(os.path.join(d, f), dest).replace(os.sep, "/")
                for d, _, fs in os.walk(dest) for f in fs)
            self.assertEqual(copied, [".gitignore", "lib/util.py", "main.py"])
            self.assertEqual(n, 3)


if __name__ == "__main__":
    unittest.main()
