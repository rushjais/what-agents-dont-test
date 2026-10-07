"""Shared loader for baselines built from the reference with some rules switched off.
Baselines may import the reference; agent solutions may not (it never enters their sandbox)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reference"))
import packignore  # noqa: E402,F401
