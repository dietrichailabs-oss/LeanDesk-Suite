"""Compatibility import surface for LeanDesk's modular update subsystem.

The implementation lives under :mod:`leandesk.updates`; this wrapper keeps the public
API used by existing builds and tests while the main application consumes the same code.
"""

from .updates import *  # noqa: F401,F403
