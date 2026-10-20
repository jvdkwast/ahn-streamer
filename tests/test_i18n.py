"""Every tr() string must have a Dutch translation, and vice versa."""

import ast
import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ahn_tiles  # noqa: E402
import i18n  # noqa: E402


def tr_strings():
    """String literals passed to tr(), plus labels translated indirectly."""
    found = set()
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.add(node.args[0].value)
    # labels from data tables that are passed to tr() as variables
    found.update(label for label, _ in ahn_tiles.CLASS_FILTERS.values())
    found.update(label for label, _ in ahn_tiles.CLASSES.values())
    renderers = [
        "Classification (AHN colours)",
        "Height above NAP",
        "Intensity",
        "Number of returns (vegetation/edges)",
        "QGIS default (RGB if present)",
    ]
    found.update(renderers)
    return found


class TestI18n(unittest.TestCase):
    def test_all_translated(self):
        missing = sorted(s for s in tr_strings() if s not in i18n.NL)
        self.assertEqual(missing, [], "untranslated strings")

    def test_no_unused_translations(self):
        unused = sorted(set(i18n.NL) - tr_strings())
        self.assertEqual(unused, [], "translations that are never used")

    def test_placeholders_match(self):
        for en, nl in i18n.NL.items():
            self.assertEqual(en.count("%"), nl.count("%"), en)

    def test_switch(self):
        i18n.set_language("nl")
        self.assertEqual(i18n.tr("%d sheets loaded", 3), "3 bladen geladen")
        i18n.set_language("en")
        self.assertEqual(i18n.tr("%d sheets loaded", 3), "3 sheets loaded")
        self.assertEqual(i18n.tr("Not in the table"), "Not in the table")


if __name__ == "__main__":
    unittest.main()
