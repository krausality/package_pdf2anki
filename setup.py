"""Legacy build shim -- ALL project metadata lives in pyproject.toml.

This file used to duplicate the dependency list. The two copies drifted, and
during the 2026-08 Dependabot incident the duplication meant every pin fix
had to be applied twice (Dependabot was reading THIS file while pip installed
from pyproject.toml). Single source of truth now: pyproject.toml [project].
Do not add install_requires (or any other [project]-covered field) back here.
"""
from setuptools import setup

setup()
