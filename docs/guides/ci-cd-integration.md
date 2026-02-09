---
title: CI/CD Integration
description: Automate dependency management with CI/CD pipelines
---

# CI/CD Integration

Integrate depkeeper into your CI/CD pipeline for automated dependency monitoring and updates.

---

## Overview

depkeeper fits into CI/CD workflows for:

- **Monitoring**: Alert when dependencies are outdated
- **Reporting**: Generate dependency reports
- **Automation**: Automatically update dependencies
- **Security**: Flag vulnerable packages (coming soon)

---

## GitHub Actions

### Check for Outdated Dependencies

Create `.github/workflows/dependency-check.yml`:

```yaml
name: Dependency Check

on:
  schedule:
    # Run every Monday at 9 AM UTC
    - cron: '0 9 * * 1'
  workflow_dispatch:  # Manual trigger

jobs:
  check:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install depkeeper
        run: pip install depkeeper

      - name: Check dependencies
        run: depkeeper check --format json > deps-report.json

      - name: Check for outdated
        id: outdated
        run: |
          OUTDATED=$(depkeeper check --outdated-only --format simple | wc -l)
          echo "count=$OUTDATED" >> $GITHUB_OUTPUT

      - name: Report status
        if: steps.outdated.outputs.count > 0
        run: |
          echo "⚠️ Found ${{ steps.outdated.outputs.count }} outdated dependencies"
          depkeeper check --outdated-only --format table

      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: dependency-report
          path: deps-report.json
```

### Automated Dependency Updates

Create `.github/workflows/dependency-update.yml`:

```yaml
name: Dependency Update

on:
  schedule:
    - cron: '0 9 * * 1'  # Weekly on Monday
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install depkeeper
          pip install -r requirements.txt

      - name: Check for updates
        id: check
        run: |
          depkeeper check --outdated-only --format json > outdated.json
          UPDATES=$(cat outdated.json | jq length)
          echo "count=$UPDATES" >> $GITHUB_OUTPUT

      - name: Update dependencies
        if: steps.check.outputs.count > 0
        run: depkeeper update --backup -y

      - name: Run tests
        if: steps.check.outputs.count > 0
        run: pytest

      - name: Create Pull Request
        if: steps.check.outputs.count > 0
        uses: peter-evans/create-pull-request@v6
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          commit-message: 'chore(deps): update dependencies'
          title: '⬆️ Update dependencies'
          body: |
            Automated dependency updates by depkeeper.

            ## Updated packages
            $(depkeeper check --format simple)
          branch: deps/automated-updates
          delete-branch: true
```

### Fail on Outdated (Strict Mode)

For strict dependency policies:

```yaml
- name: Check dependencies (strict)
  run: |
    OUTDATED=$(depkeeper check --outdated-only --format json | jq length)
    if [ "$OUTDATED" -gt 0 ]; then
      echo "❌ $OUTDATED outdated dependencies found!"
      depkeeper check --outdated-only
      exit 1
    fi
    echo "✅ All dependencies up to date"
```

---

## GitLab CI

### `.gitlab-ci.yml`

```yaml
stages:
  - check
  - update

variables:
  PYTHON_VERSION: "3.11"

dependency-check:
  stage: check
  image: python:${PYTHON_VERSION}
  script:
    - pip install depkeeper
    - depkeeper check --format json > deps-report.json
    - depkeeper check --outdated-only
  artifacts:
    reports:
      dotenv: deps-report.json
    paths:
      - deps-report.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "web"

dependency-update:
  stage: update
  image: python:${PYTHON_VERSION}
  script:
    - pip install depkeeper
    - depkeeper update --backup -y
    - pip install -r requirements.txt
    - pytest
  artifacts:
    paths:
      - requirements.txt
      - requirements.txt.backup.*
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: manual
```

---

## Azure Pipelines

### `azure-pipelines.yml`

```yaml
trigger: none

schedules:
  - cron: '0 9 * * 1'
    displayName: Weekly dependency check
    branches:
      include:
        - main

pool:
  vmImage: 'ubuntu-latest'

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.11'

  - script: pip install depkeeper
    displayName: Install depkeeper

  - script: depkeeper check --format json > $(Build.ArtifactStagingDirectory)/deps.json
    displayName: Check dependencies

  - script: depkeeper check --outdated-only --format table
    displayName: Show outdated packages

  - task: PublishBuildArtifacts@1
    inputs:
      pathToPublish: $(Build.ArtifactStagingDirectory)/deps.json
      artifactName: dependency-report
```

---

## Jenkins

### `Jenkinsfile`

```groovy
pipeline {
    agent {
        docker {
            image 'python:3.11'
        }
    }

    triggers {
        cron('H 9 * * 1')  // Weekly on Monday
    }

    stages {
        stage('Setup') {
            steps {
                sh 'pip install depkeeper'
            }
        }

        stage('Check Dependencies') {
            steps {
                sh 'depkeeper check --format json > deps-report.json'
                sh 'depkeeper check --outdated-only'
            }
        }

        stage('Archive Report') {
            steps {
                archiveArtifacts artifacts: 'deps-report.json'
            }
        }
    }

    post {
        always {
            script {
                def outdated = sh(
                    script: 'depkeeper check --outdated-only --format simple | wc -l',
                    returnStdout: true
                ).trim()

                if (outdated.toInteger() > 0) {
                    currentBuild.description = "⚠️ ${outdated} outdated dependencies"
                }
            }
        }
    }
}
```

---

## CircleCI

### `.circleci/config.yml`

```yaml
version: 2.1

jobs:
  dependency-check:
    docker:
      - image: cimg/python:3.11
    steps:
      - checkout
      - run:
          name: Install depkeeper
          command: pip install depkeeper
      - run:
          name: Check dependencies
          command: |
            depkeeper check --format json > deps-report.json
            depkeeper check --outdated-only
      - store_artifacts:
          path: deps-report.json

workflows:
  weekly-check:
    triggers:
      - schedule:
          cron: "0 9 * * 1"
          filters:
            branches:
              only:
                - main
    jobs:
      - dependency-check
```

---

## Pre-commit Hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: depkeeper-check
        name: Check dependencies
        entry: depkeeper check --outdated-only --format simple
        language: system
        pass_filenames: false
        files: requirements.*\.txt$
```

---

## Best Practices

### 1. Weekly Checks

Schedule dependency checks weekly to stay informed without noise:

```yaml
schedule:
  - cron: '0 9 * * 1'  # Monday 9 AM
```

### 2. Separate Check and Update

Keep check and update as separate jobs:

- **Check**: Always runs, reports status
- **Update**: Manual trigger or conditional

### 3. Test After Updates

Always run your test suite after automated updates:

```yaml
- name: Update
  run: depkeeper update -y

- name: Test
  run: pytest
```

### 4. Create Pull Requests

Don't push directly to main. Create PRs for review:

```yaml
- uses: peter-evans/create-pull-request@v6
  with:
    branch: deps/updates
```

### 5. Use JSON for Processing

Use `--format json` when you need to process the output:

```bash
depkeeper check --format json | jq '.[] | select(.update_type == "patch")'
```

### 6. Notifications

Send notifications for outdated dependencies:

```yaml
- name: Notify Slack
  if: steps.check.outputs.count > 0
  uses: slackapi/slack-github-action@v1
  with:
    slack-message: "⚠️ ${{ steps.check.outputs.count }} dependencies need updates"
```

---

## Exit Codes

Use exit codes for CI logic:

| Code | Meaning | CI Action |
|---|---|---|
| `0` | Success | Continue |
| `1` | Error | Fail build |
| `2` | Usage error | Fail build |

Example:

```bash
depkeeper check || echo "Check failed with code $?"
```

---

## Next Steps

- [Configuration](configuration.md) -- Customize depkeeper behavior
- [CLI Reference](../reference/cli-commands.md) -- All command options
- [Exit Codes](../reference/exit-codes.md) -- Complete exit code reference
