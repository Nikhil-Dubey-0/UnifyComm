"""Rule registry (ARCHITECTURE §7.6.2).

Session 1 ships the engine with an empty registry (allow-all). Session 4 adds the rules
from §7.6.2 here, each with pass and fail unit tests.
"""

from app.compliance.engine import Rule

RULES: list[Rule] = []
