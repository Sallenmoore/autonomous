

from dataclasses import dataclass

@dataclass
class GHConfig:
    """Class for keeping track of VC configuration data."""
    token: str
    name: float
    username: str
    email: int = 0
    