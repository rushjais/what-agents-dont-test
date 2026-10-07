"""The reference itself. Must score 100%: checks scoring plumbing, like v1's git_wrapper."""
from _ref import packignore


def ignored_files(root):
    return packignore.ignored_files(root)
