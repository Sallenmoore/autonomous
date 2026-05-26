"""Independent coverage for PR #13 (iter/2026-05-26c: worker image
build-time deps — closes #10, #8).

PR #13 takes the worker service introduced in PR #7 and moves its
dependency closure from container-startup time into image build time.
This addresses the test agent's hygiene concern from issue #10 (filed
during the previous iter's /review-pr cycle): the prior shape ran a
full `pip install` inside the worker's `command:` on every container
start, leaking install duration into `make inittests`'s 300s ceiling,
non-idempotent on restart, and writing build artifacts into the
bind-mounted host repo via `-e .[tasks]`.

The dev perspective: "ship a `tests/worker.Dockerfile`, switch the
compose service from `image:` to `build:`, drop the heavy install
from `command:`, tighten the healthcheck retries to match the new
startup profile." The test agent's independent perspective: "is the
Dockerfile structurally sound, are the compose changes consistent
with the new shape, and do any of the migrated bits leave behind
surprises (stale references to the old image-only shape, dropped
PYTHONPATH, etc.)?"

Hermetic: filesystem reads + ``yaml.safe_load`` of the compose file.
No subprocess invocations of ``docker build``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "tests" / "worker.Dockerfile"
COMPOSE = REPO / "tests" / "docker-compose.yml"


# ---------------------------------------------------------------------------
# tests/worker.Dockerfile — new file
# ---------------------------------------------------------------------------


class TestWorkerDockerfile:
    """The new Dockerfile is the headline of PR #13. It's the layer
    that absorbs the dep-resolution cost so cold-start ``make
    inittests`` doesn't budget against a full pip resolution."""

    @classmethod
    def setup_class(cls):
        cls.text = DOCKERFILE.read_text(encoding="utf-8") if DOCKERFILE.exists() else ""
        cls.lines = cls.text.splitlines()

    def test_dockerfile_exists(self):
        assert DOCKERFILE.exists(), (
            "tests/worker.Dockerfile is missing — PR #13's whole point "
            "was to move worker dep install from container-start (the "
            "issue #10 symptom) into image-build. Without this file, "
            "the build directive in compose can't find a Dockerfile to "
            "build from."
        )

    def test_from_python_slim_baseline(self):
        """The image baseline must match the sibling test-stack
        services (python:3.13-slim was the prior `image:` value).
        A drift to e.g. python:3.13 (non-slim) silently inflates the
        image by ~150MB and makes cold-start slower than the issue #10
        symptom it was meant to fix."""
        assert re.search(
            r"^FROM\s+python:3\.13-slim\s*$", self.text, re.MULTILINE
        ), (
            "tests/worker.Dockerfile FROM line is not "
            "`python:3.13-slim`. Either a Python version drifted or "
            "the slim variant got dropped — both inflate image size "
            "and undermine the cold-start goal of PR #13."
        )

    def test_dependency_closure_installed_at_build_time(self):
        """The whole point of PR #13: requirements files installed at
        BUILD time (via RUN), not at container START time (via CMD/
        command). If a future edit silently moves them back into a CMD
        line, the issue #10 symptom returns."""
        # RUN with pip install referencing all three requirements files.
        run_pattern = re.compile(
            r"^RUN\s+.*pip\s+install\s+.*",
            re.MULTILINE,
        )
        assert run_pattern.search(self.text), (
            "tests/worker.Dockerfile has no RUN pip install — deps "
            "would be installed at container-start again, undoing "
            "PR #13."
        )
        # Verify all three of the project's requirements files are
        # referenced — partial installs would leave the worker missing
        # deps the test suite expects.
        for req in (
            "requirements.txt",
            "requirements_dev.txt",
            "requirements-tasks.txt",
        ):
            assert req in self.text, (
                f"tests/worker.Dockerfile no longer references {req}. "
                "If a dep set is dropped from build-time install, the "
                "container will reach for it at runtime and reintroduce "
                "the install-on-start regression."
            )

    def test_no_cmd_defined(self):
        """Compose drives the runtime invocation directly via its own
        `command:`; the Dockerfile deliberately has no CMD so the
        image isn't tempted to run something different when invoked
        outside compose. If someone adds a CMD as a "safety net," the
        compose `command:` still wins, but the Dockerfile's contract
        gets fuzzier."""
        assert not re.search(
            r"^CMD\b", self.text, re.MULTILINE
        ), (
            "tests/worker.Dockerfile now defines a CMD — that's a "
            "deviation from PR #13's design intent ('No CMD' is "
            "spelled out in the Dockerfile comments). Compose still "
            "overrides it, but adding dead/conflicting state weakens "
            "the file's self-documenting shape."
        )

    def test_workdir_matches_compose_bind_mount(self):
        """The Dockerfile sets WORKDIR /var/app/autonomous; the
        compose bind-mount lands the repo at the same path. If they
        drift, the editable install at container-start (`pip install
        -e .[tasks]`) goes against the wrong directory and either
        no-ops or installs a phantom package."""
        assert re.search(
            r"^WORKDIR\s+/var/app/autonomous\s*$",
            self.text,
            re.MULTILINE,
        ), (
            "tests/worker.Dockerfile WORKDIR no longer matches the "
            "compose bind-mount target (/var/app/autonomous). The "
            "editable install at container-start would target the "
            "wrong directory."
        )


# ---------------------------------------------------------------------------
# tests/docker-compose.yml — worker service migrated to build directive
# ---------------------------------------------------------------------------


class TestComposeWorkerUsesBuildDirective:
    """PR #13 switches the worker from a bare `image:` to a `build:`
    directive pointing at the new Dockerfile. The previous shape
    (`image: python:3.13-slim` + heavy `command:`) reintroduces
    issue #10 if rolled back without warning."""

    @classmethod
    def setup_class(cls):
        parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        cls.worker = (parsed.get("services") or {}).get("worker") or {}

    def test_worker_uses_build_not_bare_image(self):
        assert "build" in self.worker, (
            "tests/docker-compose.yml worker service no longer "
            "declares a `build:` section — it likely regressed to the "
            "pre-PR-#13 bare `image:` form, which reintroduces the "
            "container-start install behaviour issue #10 documented."
        )
        # Forbid the bare image key when build is present — they'd
        # both be ignored or one would silently override the other.
        # The cleaner shape is build-only.
        if "image" in self.worker:
            # image alongside build is allowed in compose (image becomes
            # the build-output tag) but only if it's not a pre-built
            # baseline like python:3.13-slim (which would tell the user
            # the build directive is dead/ignored).
            image_ref = self.worker["image"]
            assert not image_ref.startswith("python:"), (
                f"compose worker.image is {image_ref!r} alongside "
                "`build:` — looks like a half-rolled-back edit. "
                "Either drop `image:` (and let build name the result) "
                "or drop `build:` (and own the consequences)."
            )

    def test_build_context_is_repo_root(self):
        """The Dockerfile COPYs requirements.txt etc. via paths
        relative to the repo root, so the build context must be `..`
        (relative to tests/docker-compose.yml). A drift to `.` would
        try to COPY tests/requirements.txt — which doesn't exist."""
        build = self.worker["build"]
        assert isinstance(build, dict), (
            "compose worker.build collapsed from long-form to short-"
            "form (string). The Dockerfile COPYs need the explicit "
            "long-form context override."
        )
        assert build.get("context") == "..", (
            f"compose worker.build.context is {build.get('context')!r}, "
            "expected `..` — the Dockerfile's COPY paths are repo-"
            "root-relative."
        )

    def test_build_dockerfile_path_matches_filename(self):
        build = self.worker["build"]
        assert build.get("dockerfile") == "tests/worker.Dockerfile", (
            "compose worker.build.dockerfile no longer points at "
            "tests/worker.Dockerfile — a rename or path drift would "
            "send `docker compose build` looking for the file at a "
            "non-existent location, breaking `make inittests`."
        )


class TestComposeWorkerCommandSlimmed:
    """With the heavy install now in the image layer, the compose-
    level `command:` should only do the lightweight editable install
    of the bind-mounted source + start rq. If `requirements_dev.txt`
    sneaks back into the command line, the install-on-start regression
    returns."""

    @classmethod
    def setup_class(cls):
        parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        cls.worker = (parsed.get("services") or {}).get("worker") or {}
        command = cls.worker.get("command") or []
        cls.command_text = (
            " ".join(command) if isinstance(command, list) else str(command)
        )

    def test_command_still_runs_rq_worker(self):
        assert "rq worker" in self.command_text, (
            "compose worker.command no longer invokes `rq worker` — "
            "the worker container is up but consuming nothing from the "
            "queue. Issue #5's symptom returns."
        )

    def test_command_still_runs_editable_install_of_self(self):
        """The bind-mounted source needs `pip install -e .[tasks]`
        at startup so the locally-edited package code is what the
        worker uses. If this drops, the worker runs against an empty
        site-packages (no `autonomous` module) and rq's
        `import_attribute` can't resolve the task functions."""
        assert re.search(
            r"pip\s+install\s+(?:--no-cache-dir\s+)?-e\s+\.\[tasks\]",
            self.command_text,
        ), (
            "compose worker.command no longer does the editable "
            "install of .[tasks] — the bind-mounted source won't be "
            "importable in the container at runtime."
        )

    def test_command_does_not_install_requirements_dev(self):
        """The whole point of PR #13: heavy install moves OFF
        container-start. If requirements_dev.txt sneaks back into
        the command, the install duration leaks back into the
        startup-time budget and issue #10 returns."""
        assert "requirements_dev.txt" not in self.command_text, (
            "compose worker.command re-introduces "
            "`-r requirements_dev.txt` — that install now happens at "
            "BUILD time per tests/worker.Dockerfile. Running it again "
            "at container-start undoes PR #13."
        )

    def test_pythonpath_preserved(self):
        """rq's `import_attribute` resolves bare module names like
        `test_int_tasks.mytask` for pytest-enqueued jobs. The compose
        worker sets PYTHONPATH explicitly to include both the package
        root and tests/integration so those imports work. If a refactor
        drops it, the worker comes up but every job fails with
        ImportError."""
        env = self.worker.get("environment") or {}
        pythonpath = env.get("PYTHONPATH", "")
        assert "/var/app/autonomous/tests/integration" in pythonpath, (
            "compose worker.environment.PYTHONPATH no longer includes "
            "/var/app/autonomous/tests/integration — rq's "
            "import_attribute() will fail to resolve the bare module "
            "names that pytest-enqueued jobs carry, and every "
            "integration task fails with ImportError."
        )


class TestComposeWorkerHealthcheckTightened:
    """PR #13 tightens retries 60→24 and start_period 30s→15s because
    the new startup profile is image-pull + a fast editable install.
    If the healthcheck regresses to the loose old values, it'd be
    benign (still works) but hides any future cold-start regressions."""

    @classmethod
    def setup_class(cls):
        parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        cls.worker = (parsed.get("services") or {}).get("worker") or {}
        cls.healthcheck = cls.worker.get("healthcheck") or {}

    def test_healthcheck_present(self):
        assert self.healthcheck, (
            "compose worker.healthcheck regressed away — without it, "
            "compose reports the container 'up' before rq registers "
            "with Redis, breaking the makefile's SCARD-based wait."
        )

    def test_healthcheck_uses_scard_signal(self):
        """The healthcheck must read `rq:workers` via SCARD to confirm
        the worker has actually registered (rather than just that the
        container process is alive). A regression to a generic
        `CMD-SHELL exit 0` would mask broken registration."""
        test_cmd = self.healthcheck.get("test", [])
        cmd_str = " ".join(test_cmd) if isinstance(test_cmd, list) else str(test_cmd)
        assert "scard" in cmd_str.lower() and "rq:workers" in cmd_str, (
            "compose worker.healthcheck no longer probes "
            "redis.scard('rq:workers') — the readiness signal is "
            "decoupled from actual worker registration, masking real "
            "failures."
        )

    def test_retries_bounded(self):
        """Retries should be in the low tens — 24 in PR #13. A jump
        back to 60 (the pre-PR-#13 value) would suggest the cold-start
        budget is being expanded to absorb a regression rather than
        the image-build absorbing the install cost."""
        retries = self.healthcheck.get("retries")
        assert retries is not None, (
            "compose worker.healthcheck.retries is unset — defaults to "
            "3, far below the post-build-pull register time."
        )
        assert retries <= 30, (
            f"compose worker.healthcheck.retries is {retries}, suggesting "
            "the cold-start budget grew back toward pre-PR-#13 levels. "
            "Build-time dep install was supposed to TIGHTEN this."
        )

    def test_start_period_tight(self):
        sp = self.healthcheck.get("start_period")
        assert sp is not None, (
            "compose worker.healthcheck.start_period is unset — "
            "containers report unhealthy during the initial grace "
            "window, confusing depends_on conditions in CI."
        )
        # start_period is a duration string like "15s" — extract the
        # numeric part and compare in seconds.
        match = re.match(r"^(\d+(?:\.\d+)?)\s*s$", str(sp))
        assert match, (
            f"compose worker.healthcheck.start_period is {sp!r}, "
            "unparseable as seconds. PR #13 set this to 15s."
        )
        assert float(match.group(1)) <= 20, (
            f"compose worker.healthcheck.start_period is {sp}, "
            "loosened back toward the pre-PR-#13 30s. Build-time "
            "install should have made this tighter, not looser."
        )
