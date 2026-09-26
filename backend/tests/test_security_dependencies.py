"""Prevent deployment with the known-vulnerable Starlette form parser version."""
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


def test_starlette_runtime_contains_form_parser_limit_fix():
    assert Version(version("starlette")) >= Version("1.3.1")


def test_runtime_requirements_pin_a_patched_starlette():
    path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements = [Requirement(line) for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    pins = [requirement for requirement in requirements if requirement.name == "starlette"]
    assert len(pins) == 1
    assert not pins[0].specifier.contains("1.2.1")
    assert pins[0].specifier.contains("1.3.1")
