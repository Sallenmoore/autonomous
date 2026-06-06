---
description: Run one iteration of the autonomous test cycle.
---

You are the **autonomous-test** agent. The canonical procedure lives at:

    /opt/stacks/agent-runner/templates/test-agent.md

Read that file now and execute it step-by-step with these project values:

- PROJECT = autonomous
- PROJECT_UPPER = AUTONOMOUS (drives the AUTONOMOUS_CYCLE: sentinel)
- REPO = Sallenmoore/autonomous
- BRANCH_DEV = dev
- BRANCH_TEST = test
- BRANCH_MAIN = main
- TEST_CMD = python -m pytest
- (no `containers.test:` — skip the §0 ${CONTAINER_TEST}-down preflight)
- LABEL_ENHANCEMENT = feature-request
- LABEL_HUMAN_ONLY = human-only
- LABEL_AWAITING_UPSTREAM = awaiting-upstream

Project-specific notes:
- Autonomous has no e2e/playwright gate; skip the storyteller-ism in §5
  that runs `docker exec stdev sh -c 'cd /var/app && npx playwright ...'`.
