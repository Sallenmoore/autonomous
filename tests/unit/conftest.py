"""Unit-test conftest.

Historical note: this file used to skip the pydub-dependent suites on
Python 3.13+ because pydub's `import audioop` exploded on 3.13 (PEP 594
removed audioop from stdlib). PR #37 / issue #24 fixed that at the dep
layer by pinning `audioop-lts` in requirements-ai.txt, so the skip
block is no longer needed — the affected tests now run cleanly on
every leg of the matrix.
"""
