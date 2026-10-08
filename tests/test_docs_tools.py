"""The generated action reference and the feasibility explainer stay in sync with the code."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_action_has_a_controller_and_a_meaning():
    ar = _load("action_reference")
    acts = set(ar.ACTION_SPECS)
    assert acts == set(ar.REGISTRY) == set(ar.MEANING) == set(ar.CATEGORY)


def test_actions_doc_is_up_to_date():
    doc = (ROOT / "docs" / "ACTIONS.md").read_text()
    ar = _load("action_reference")
    assert all(f"| `{a}` |" in doc for a in ar.ACTION_SPECS), "run python scripts/action_reference.py"


def test_explain_feasibility_runs():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "explain_feasibility.py"), "--play",
                          "third_man_combination", "--detail"], capture_output=True, text=True, timeout=300, check=True)
    assert "third_man_combination" in out.stdout and "3 roles" in out.stdout and "plays feasible" in out.stdout
