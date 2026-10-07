"""Truth with exactly one rule switched off; the rule is chosen by the MISSED env var.
Used to check that each bucket isolates its rule: missing rule R should fail
bucket R and pass every other bucket."""
import os

from _ref import packignore


def ignored_files(root):
    return packignore.ignored_files(root, packignore.ABLATIONS[os.environ["MISSED"]])
