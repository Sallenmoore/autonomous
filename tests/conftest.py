import sys
from pathlib import Path

# Containerized CI path.
sys.path.insert(0, "/var/app/autonomous")

# Local checkout: put src/ on the path so `import autonomous` works from a
# non-installed source tree. Harmless when running in the container.
_repo_src = Path(__file__).resolve().parents[1] / "src"
if _repo_src.is_dir():
    sys.path.insert(0, str(_repo_src))
