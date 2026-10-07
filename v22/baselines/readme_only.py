"""What you get by trusting the README and assuming gitignore-like behavior for
everything it doesn't say: '#' comments, last match wins, unlimited '**',
no re-inclusion inside excluded dirs, no braces."""
from _ref import packignore


def ignored_files(root):
    return packignore.ignored_files(root, packignore.README_ONLY)
