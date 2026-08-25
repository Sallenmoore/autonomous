#!/usr/bin/env python3
"""Assert what PyPI does (or does not) already hold for a version.

``make package`` uploads with ``twine upload --skip-existing``. That flag
makes a re-upload of an existing version a silent no-op: twine exits 0,
``release.sh`` commits the bump, pushes ``main`` and prints ✅ — and PyPI
never received the artifact. The repo then believes a version shipped that
consumers cannot install. Nothing downstream of the upload noticed, because
nothing downstream of the upload *asked*.

This is that question, in two directions:

* ``--assert-absent`` before building — the version we are about to publish
  must be new, or ``--skip-existing`` will swallow the upload.
* ``--assert-present`` after uploading — the version must now actually be on
  the index.

Exit codes are the contract ``release.sh`` branches on: ``0`` verdict holds,
``1`` verdict is definitely violated, ``2`` PyPI could not be read. ``2`` is
deliberately NOT an error — a flaky index read should warn, not strand a
release or block one on a transient outage.
"""

import argparse
import json
import sys
import urllib.request

PYPI_JSON = "https://pypi.org/pypi/{package}/json"

EXIT_CODES = {"ok": 0, "fail": 1, "unknown": 2}


def fetch_versions(package, *, timeout=15, opener=urllib.request.urlopen):
    """Every version PyPI lists for ``package``, or ``None`` if unreadable.

    ``None`` rather than an exception or an empty set, because the caller
    must be able to tell "PyPI says this version does not exist" from "could
    not ask PyPI" — treating the second as the first would let a network
    blip green-light a release that published nothing.
    """
    try:
        with opener(PYPI_JSON.format(package=package), timeout=timeout) as resp:
            return set(json.load(resp).get("releases", {}))
    except Exception:
        # ponytail: every failure mode here (DNS, TLS, 404, HTML error page,
        # truncated body) means the same thing to the caller — no answer.
        return None


def check(package, version, expect, *, fetch=fetch_versions):
    """``"ok"`` / ``"fail"`` / ``"unknown"`` for ``expect`` in {absent, present}."""
    versions = fetch(package)
    if versions is None:
        return "unknown"
    present = version in versions
    wanted = present if expect == "present" else not present
    return "ok" if wanted else "fail"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package")
    ap.add_argument("version")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--assert-absent", action="store_true")
    group.add_argument("--assert-present", action="store_true")
    args = ap.parse_args(argv)

    expect = "present" if args.assert_present else "absent"
    verdict = check(args.package, args.version, expect)

    if verdict == "unknown":
        print(
            f"⚠️  Could not read PyPI for {args.package}; "
            f"cannot confirm {args.version} is {expect}.",
            file=sys.stderr,
        )
    elif verdict == "fail" and expect == "absent":
        print(
            f"❌ {args.package} {args.version} is ALREADY on PyPI. "
            "`twine upload --skip-existing` would publish nothing while "
            "reporting success. Bump to an unused version.",
            file=sys.stderr,
        )
    elif verdict == "fail":
        print(
            f"❌ {args.package} {args.version} is NOT on PyPI after upload — "
            "the release did not actually publish.",
            file=sys.stderr,
        )
    return EXIT_CODES[verdict]


if __name__ == "__main__":
    sys.exit(main())
