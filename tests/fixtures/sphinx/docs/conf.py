import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

project = "fixture"
extensions = ["sphinx.ext.autodoc"]
html_theme = "alabaster"
