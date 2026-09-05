"""HabitusX: the AI Code Outcomes Index.

Measures what happens to AI-written code after it lands in public repositories:
reverts, follow-up fixes, pull request acceptance and survival, broken down by
agent, language and repository. Neutral, continuous, methodology published.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("habitusx")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
