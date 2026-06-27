"""MCP server for the Standoff 365 Bug Bounty platform."""

from .client import Sf365Client, Sf365Error

__all__ = ["Sf365Client", "Sf365Error"]
__version__ = "0.1.0"
