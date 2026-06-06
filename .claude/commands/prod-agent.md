---
description: Run one iteration of the autonomous prod release.
---

You are the **autonomous-prod** agent. The canonical procedure lives at:

    /opt/stacks/agent-runner/templates/prod-agent.md

Read that file now and execute it step-by-step with these project values:

- PROJECT = autonomous
- REPO = Sallenmoore/autonomous
- BRANCH_DEV = dev
- BRANCH_TEST = test
- BRANCH_MAIN = main
- DEPLOY_TYPE = pypi             (so §4 uses the pypi-branch deploy)
- DEPLOY_CMD = scripts/release.sh
- VERIFY_TYPE = pypi_probe       (so §5 uses pypi-probe + smoke verify)
- PYPI_PACKAGE = autonomous-app
- SMOKE_CMD = scripts/smoke_test.sh
- (no `containers.prod:` — autonomous is a library; skip §0 prod-stack-down preflight)

Project-specific notes:
- (none — the template carries autonomous's release+smoke flow via the
  pypi branch.)
