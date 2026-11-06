---
title: CI/CD Integration
description: Running depkeeper in pipelines — drift reports, gating, automated update pull requests
---

# CI/CD Integration

depkeeper is designed for non-interactive use: machine-readable output on stdout, diagnostics on
stderr, and deterministic exit codes.

Three patterns cover almost every pipeline need:

| Pattern | Command shape | Purpose |
|---|---|---|
| **Report** | `check --format json` (or `markdown`) | Publish drift as an artefact or job summary. Does not fail the build on updates. |
| **Gate** | `check --fail-on LEVEL` | Fail the build (exit `3`) when updates at that level exist. |
| **Propose** | `update -y --verify` + open a pull request | Automate the upgrade itself, with human review. |

---

## Fundamentals

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Completed. Without `--fail-on`, updates do **not** change this. |
| `1` | Error (parse, config, write, refused hashes, `update --verify` conflict, declined prompt). |
| `2` | Usage error. |
| `3` | `check --fail-on`: updates at or above the level exist (`updates` = any, `minor` = minor or major, `major` = major only). |
| `4` | A package could not be looked up on PyPI (wins over `3`; `update` also returns it). |

Gate directly with the flag, or set `fail_on` in the config file:

```bash
depkeeper check --fail-on minor --format json > report.json
case $? in
  0) echo "ok" ;;
  3) echo "updates available"; exit 1 ;;
  *) echo "depkeeper failed (see depkeeper.log)"; exit 1 ;;   # 1, 2, 4
esac
```

To apply your own threshold, run without `--fail-on` (exit `0` means success) and parse the JSON
payload. Full table: [Exit codes](../reference/exit-codes.md).

### Pin the depkeeper version

Recommendation logic is behaviour. An unpinned install can change your pipeline's verdict without
any change to your repository.

```bash
python -m pip install --no-cache-dir "depkeeper==0.1.1"
```

### Match the interpreter

depkeeper filters candidate versions for one target Python: `--python-version`, else the
config `python_version`, else the file's `requires-python` / conda `python` pin (lowest supported
minor), else **the interpreter running depkeeper**. Set one of the first three, or run it on the
Python your project targets. See
[Python compatibility](../concepts/version-recommendation.md#python-compatibility-filtering).

### Keep stdout clean

```bash
depkeeper -v check --format json > report.json 2> depkeeper.log
```

Both streams stay useful: a parseable payload and a full diagnostic log to attach on failure.

### Disable colour explicitly

```bash
export NO_COLOR=1
```

depkeeper already disables ANSI in log records when `CI` is set, and disables colour on
non-TTY streams, but an explicit `NO_COLOR=1` removes all ambiguity.

### Reduce request volume

`--no-check-conflicts` removes the resolution phase, which is the dominant source of PyPI
requests. Use it for pure drift reports; keep it enabled when the pipeline applies updates.

---

## GitHub Actions

### Scheduled drift report

```yaml
name: Dependency drift

on:
  schedule:
    - cron: "0 6 * * 1"     # Mondays 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"     # must match the project's target

      - name: Install depkeeper
        run: python -m pip install --no-cache-dir "depkeeper==0.1.1"

      - name: Generate report
        env:
          NO_COLOR: "1"
        run: |
          # exit 4 = a package could not be looked up; the report is still written
          depkeeper -v check --format json > depkeeper-report.json 2> depkeeper.log || [ $? -eq 4 ]

      - name: Summarise
        run: |
          jq -r '
            "| Package | Current | Recommended | Type |",
            "|---|---|---|---|",
            (.[] | select(.status == "outdated")
              | "| \(.name) | \(.versions.current // "-") | \(.versions.recommended) | \(.update_type) |")
          ' depkeeper-report.json >> "$GITHUB_STEP_SUMMARY"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: depkeeper-report
          path: |
            depkeeper-report.json
            depkeeper.log
```

A ready-made summary is also available: `depkeeper check --format markdown >> "$GITHUB_STEP_SUMMARY"`.

### Gate a pull request on drift policy

```yaml
name: Dependency gate

on: [pull_request]

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install --no-cache-dir "depkeeper==0.1.1"

      - name: Fail on major updates
        env:
          NO_COLOR: "1"
        # exit 3: a major update is proposed; exit 4: PyPI lookup failed; 1/2: depkeeper error
        run: depkeeper check --fail-on major

      - name: Fail on unresolved conflicts
        env:
          NO_COLOR: "1"
        run: |
          depkeeper check --format json > report.json
          CONFLICTS=$(jq '[.[] | select(.conflicts)] | length' report.json)
          if [ "$CONFLICTS" -gt 0 ]; then
            echo "::error::$CONFLICTS package(s) have dependency conflicts"
            jq -r '.[] | select(.conflicts) | "\(.name): \(.conflicts[].source_package) needs \(.conflicts[].required_spec)"' report.json
            exit 1
          fi

      - name: Warn on excessive drift
        run: |
          OUTDATED=$(jq '[.[] | select(.status == "outdated")] | length' report.json)
          echo "::notice::$OUTDATED package(s) behind"
          if [ "$OUTDATED" -gt 20 ]; then
            echo "::error::Dependency drift exceeds policy (>20)"
            exit 1
          fi
```

### Automated update pull request

```yaml
name: Dependency update

on:
  schedule:
    - cron: "0 7 * * 1"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install --no-cache-dir "depkeeper==0.1.1"

      - name: Apply safe updates
        env:
          NO_COLOR: "1"
        run: |
          # --verify aborts (exit 1, nothing written) if pip cannot resolve the result
          depkeeper -v update -y --verify --format markdown > pr-body.md 2> depkeeper.log

      - name: Verify the result installs and passes tests
        run: |
          python -m pip install -r requirements.txt
          python -m pytest

      - uses: peter-evans/create-pull-request@v6
        with:
          branch: chore/dependency-update
          title: "chore(deps): safe dependency updates"
          commit-message: "chore(deps): apply depkeeper safe updates"
          body-path: pr-body.md
          labels: dependencies
          delete-branch: true
```

> [!CAUTION]
> **Never skip the verification step**
>
> depkeeper does not resolve the transitive graph itself. `--verify` asks pip to dry-run the plan,
> but only the install and test step proves your code still works with it. See [Conflict resolution → What is not checked](../concepts/conflict-resolution.md#what-is-not-checked).

---

## GitLab CI

```yaml
variables:
  NO_COLOR: "1"

dependency-report:
  image: python:3.12-slim
  stage: test
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  before_script:
    - apt-get update -qq && apt-get install -y -qq jq
    - pip install --no-cache-dir "depkeeper==0.1.1"
  script:
    - depkeeper -v check --format json > report.json 2> depkeeper.log || [ $? -eq 4 ]
    - jq -r '.[] | select(.status=="outdated") | "\(.name) \(.versions.current // "-") -> \(.versions.recommended)"' report.json
  artifacts:
    when: always
    paths: [report.json, depkeeper.log]
    expire_in: 30 days
```

---

## Jenkins

```groovy
pipeline {
  agent any
  environment { NO_COLOR = '1' }
  stages {
    stage('Dependency drift') {
      steps {
        sh '''
          python -m pip install --no-cache-dir "depkeeper==0.1.1"
          depkeeper -v check --format json > report.json 2> depkeeper.log || [ $? -eq 4 ]
        '''
        script {
          def outdated = sh(
            script: "jq '[.[] | select(.status == \"outdated\")] | length' report.json",
            returnStdout: true).trim() as Integer
          if (outdated > 20) {
            unstable("Dependency drift: ${outdated} packages behind")
          }
        }
      }
      post {
        always { archiveArtifacts artifacts: 'report.json,depkeeper.log' }
      }
    }
  }
}
```

---

## pre-commit

Run `check` locally before a commit lands. Keep it informational: without `--fail-on` it exits `0`
when updates exist, but a PyPI lookup failure exits `4` and blocks the commit, so skip the hook
offline (`SKIP=depkeeper-check git commit`).

```yaml
- repo: local
  hooks:
    - id: depkeeper-check
      name: depkeeper check
      entry: depkeeper check --outdated-only --format simple
      language: system
      files: ^requirements.*\.txt$
      pass_filenames: false
      verbose: true
```

---

## Docker

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir "depkeeper==0.1.1"
WORKDIR /work
ENV NO_COLOR=1
ENTRYPOINT ["depkeeper"]
```

```bash
docker run --rm -v "$PWD:/work" depkeeper-image check --format json
```

Mount read-write only when running `update`. For `check`, mount read-only:

```bash
docker run --rm -v "$PWD:/work:ro" depkeeper-image check
```

---

## Useful `jq` recipes

```bash
# Count by status
jq 'group_by(.status) | map({status: .[0].status, count: length})' report.json

# Only packages whose recommendation is below latest (capped by a rule)
jq '[.[] | select(.versions.recommended != .versions.latest and .status == "outdated")]' report.json

# Packages that could not be reached
jq -r '.[] | select(.error) | .name' report.json

# Markdown table of proposed changes
jq -r '.[] | select(.status=="outdated") | "- `\(.name)` \(.versions.current) → \(.versions.recommended) (\(.update_type))"' report.json

# Prometheus-style metric
echo "depkeeper_outdated_packages $(jq '[.[] | select(.status == "outdated")] | length' report.json)"
```

---

## Pipeline failure modes

| Symptom | Cause | Mitigation |
|---|---|---|
| Empty or unparseable stdout | The command failed (exit `1`/`2`) before producing a payload, or stderr was merged into stdout (`2>&1`). | Redirect stderr separately; check the exit code before parsing. |
| Job fails with exit `4` | A package is not on pypi.org (private index) or PyPI was unreachable. | `--ignore` the private package, or fix egress. |
| Job fails with exit `3` | `--fail-on` / `fail_on` tripped. | Intended; raise the threshold or update. |
| Sporadic `Rate limit exceeded after 5 retries` | Many parallel jobs hitting PyPI from one egress IP. | Stagger schedules; use `--no-check-conflicts`; split large files. |
| Recommendations differ between the pipeline and a laptop | Different target Python. | Set `--python-version` / `python_version`, or declare `requires-python`. |
| Every package reports `[ERROR]` | No egress to `pypi.org`, or TLS interception. | See [Operations → TLS and proxies](operations.md#tls-and-proxies). |
| Automated PR fails `pip install` | Transitive conflict depkeeper cannot see (or `--verify` was skipped with a warning). | Keep `--verify` and the install step; add the transitive package to the file. |
