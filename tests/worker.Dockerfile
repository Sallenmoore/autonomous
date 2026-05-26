# Worker image for tests/docker-compose.yml's `worker` service.
#
# Pre-installs the dependency closure at build time so container startup
# does only a fast editable install of the autonomous package itself
# (the source is bind-mounted from the host repo at runtime). This keeps
# `make inittests` cold-start budget independent of pip resolution
# latency — important because the makefile polls for worker registration
# with a 300s ceiling and a cold pip cache can flirt with that limit.
#
# Build context is the repo root (set in tests/docker-compose.yml via
# build.context: ..) so the COPY paths below are relative to repo root,
# not to tests/.

FROM python:3.13-slim

WORKDIR /var/app/autonomous

# Layer 1: dependency closure. Re-runs only when these requirements
# files change, so the heavy install is amortized across iterations.
COPY requirements.txt requirements_dev.txt requirements-tasks.txt ./
RUN pip install --no-cache-dir \
    -r requirements.txt \
    -r requirements_dev.txt \
    -r requirements-tasks.txt

# Runtime: the repo gets bind-mounted over /var/app/autonomous in
# docker-compose.yml, so pip install -e .[tasks] just registers the
# editable autonomous package against already-installed deps (~5s).
CMD ["sh", "-c", "pip install --no-cache-dir -e .[tasks] && exec rq worker high default low --url redis://cachedb:6379"]
