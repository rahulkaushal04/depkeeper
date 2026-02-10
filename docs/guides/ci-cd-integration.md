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

      - name: Check dependencies and report
        run: |
          echo "Checking for outdated dependencies:"
          depkeeper check src/requirements.txt --outdated-only --format table

          # Fail if outdated dependencies are found
          if depkeeper check src/requirements.txt --outdated-only --format json 2>/dev/null | grep -q '"status": "outdated"'; then
            echo ""
            echo "❌ Build failed: Outdated dependencies detected. Please update them."
            exit 1
          fi
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

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          sudo apt-get update && sudo apt-get install -y jq
          pip install depkeeper
          pip install -r src/requirements.txt

      - name: Check for updates
        id: check
        run: |
          depkeeper check src/requirements.txt --outdated-only --format json > outdated.json
          echo "count=$(cat outdated.json | jq length)" >> $GITHUB_OUTPUT

      - name: Update dependencies
        if: steps.check.outputs.count > 0
        run: depkeeper update src/requirements.txt -y

      - name: Run tests
        if: steps.check.outputs.count > 0
        run: |
          cd src
          pytest

      - name: Generate update report
        if: steps.check.outputs.count > 0
        run: |
          echo "UPDATES_LIST<<EOF" >> $GITHUB_ENV
          cat outdated.json | jq -r '.[] | "- **\(.name)**: \(.versions.current) → \(.versions.recommended)"'
          echo "EOF" >> $GITHUB_ENV

      - name: Commit and push changes
        if: steps.check.outputs.count > 0
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git checkout -b deps/automated-updates
          git add src/requirements.txt
          git commit -m "chore(deps): update dependencies"
          git push -f origin deps/automated-updates

      - name: Create Pull Request
        if: steps.check.outputs.count > 0
        uses: actions/github-script@v7
        with:
          script: |
            const { data: pulls } = await github.rest.pulls.list({
              owner: context.repo.owner,
              repo: context.repo.repo,
              head: `${context.repo.owner}:deps/automated-updates`,
              state: 'open'
            });

            const prBody = `Automated dependency updates by depkeeper.

            ## Updated packages
            ${process.env.UPDATES_LIST}`;

            if (pulls.length === 0) {
              await github.rest.pulls.create({
                owner: context.repo.owner,
                repo: context.repo.repo,
                title: '⬆️ Update dependencies',
                head: 'deps/automated-updates',
                base: 'master',
                body: prBody
              });
            } else {
              await github.rest.pulls.update({
                owner: context.repo.owner,
                repo: context.repo.repo,
                pull_number: pulls[0].number,
                body: prBody
              });
            }
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
    - depkeeper check src/requirements.txt --outdated-only --format json > deps-report.json || true
    - depkeeper check src/requirements.txt --outdated-only --format table || true
  artifacts:
    paths:
      - deps-report.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "web"

dependency-update:
  stage: update
  dependencies: [dependency-check]
  image: python:${PYTHON_VERSION}
  script:
    - pip install depkeeper pytest
    - |
      COUNT=$(python -c "import json,sys; data=open('deps-report.json').read().strip(); print(len(json.loads(data)) if data else 0)" 2>/dev/null || echo "0")
      if [ "$COUNT" -eq 0 ]; then
        echo "No outdated dependencies. Skipping update."
        exit 0
      fi
    - depkeeper update src/requirements.txt --backup -y
    - pip install -r src/requirements.txt
    - cd src && pytest
  artifacts:
    paths:
      - src/requirements.txt
      - src/requirements.txt.backup.*
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: manual
    - if: $CI_PIPELINE_SOURCE == "web"
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

  - script: |
      depkeeper check src/requirements.txt --outdated-only --format json \
        > $(Build.ArtifactStagingDirectory)/deps.json || true
    displayName: Check dependencies (JSON report)

  - script: |
      depkeeper check src/requirements.txt --outdated-only --format table || true
    displayName: Show outdated packages

  - task: PublishBuildArtifacts@1
    condition: always()
    inputs:
      pathToPublish: '$(Build.ArtifactStagingDirectory)'
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
                sh 'apt-get update && apt-get install -y jq'
                sh 'pip install depkeeper'
            }
        }

        stage('Check Dependencies') {
            steps {
                sh '''
                    depkeeper check src/requirements.txt --outdated-only --format json \
                        > deps-report.json || echo "[]" > deps-report.json
                '''
                sh 'depkeeper check src/requirements.txt --outdated-only --format table || true'
            }
        }

        stage('Archive Report') {
            steps {
                archiveArtifacts allowEmptyArchive: true, artifacts: 'deps-report.json'
            }
        }
    }

    post {
        always {
            script {
                if (fileExists('deps-report.json')) {
                    def outdated = sh(
                        script: 'jq length deps-report.json || echo 0',
                        returnStdout: true
                    ).trim()

                    if (outdated.toInteger() > 0) {
                        currentBuild.description = "⚠️ ${outdated} outdated dependencies"
                    }
                } else {
                    echo "deps-report.json not found — skipping outdated count."
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
          name: Export outdated deps as JSON
          command: depkeeper check src/requirements.txt --outdated-only --format json > deps-report.json || true
      - run:
          name: Show outdated deps as table
          command: depkeeper check src/requirements.txt --outdated-only --format table || true
      - store_artifacts:
          path: deps-report.json
          destination: deps-report.json

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
        entry: depkeeper check src/requirements.txt --outdated-only --format table
        language: system
        pass_filenames: false
        files: requirements\.txt$
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
  run: depkeeper update src/requirements.txt -y

- name: Install updated packages
  run: pip install -r src/requirements.txt

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
depkeeper check src/requirements.txt --format json | jq '.[] | select(.update_type == "patch")'
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
depkeeper check src/requirements.txt || echo "Check failed with code $?"
```

---

## Next Steps

- [Configuration](configuration.md) -- Customize depkeeper behavior
- [CLI Reference](../reference/cli-commands.md) -- All command options
- [Exit Codes](../reference/exit-codes.md) -- Complete exit code reference
