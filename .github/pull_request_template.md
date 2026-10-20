## Summary

<!-- What does this change and why? -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation / tests / CI only

## Test plan

<!-- How did you verify this? Commands run, edge cases checked. -->

- [ ]

## Checklist

- [ ] `make test` passes locally (unit tier, no containers)
- [ ] `make test-int` run if this touches DB / Redis / AI code paths
- [ ] Consumer-visible change: `MIGRATIONS.md` entry added (`__version__` is bumped by `scripts/release.sh` after the merge to `main`, not in the PR)
