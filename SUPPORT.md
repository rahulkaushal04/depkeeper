# Support

How to get help with depkeeper, and where each kind of request belongs.

---

## Before asking

Most questions are answered by one of these, in order:

1. **[Troubleshooting guide](https://rahulkaushal04.github.io/depkeeper/guides/troubleshooting/)** —
   symptom-indexed diagnosis for the errors you are most likely to hit.
2. **[Known limitations](https://rahulkaushal04.github.io/depkeeper/reference/limitations/)** —
   surprising behaviour is often documented and intentional, with a workaround.
3. **[FAQ](https://rahulkaushal04.github.io/depkeeper/community/faq/)**.
4. **Your own diagnostics:**

   ```bash
   depkeeper -vv check --format json > report.json 2> debug.log
   ```

   `debug.log` names the file parsed, the effective configuration, every HTTP retry and every
   resolution decision.

---

## Where to go

| Need | Channel |
|---|---|
| Usage question, "is this expected?", design discussion | [GitHub Discussions](https://github.com/rahulkaushal04/depkeeper/discussions) |
| Reproducible defect | [Issues → Bug report](https://github.com/rahulkaushal04/depkeeper/issues/new?template=bug_report.md) |
| Feature or enhancement | [Issues → Feature request](https://github.com/rahulkaushal04/depkeeper/issues/new?template=feature_request.md) |
| Security vulnerability | **[SECURITY.md](SECURITY.md)** — never a public issue |
| Code of Conduct concern | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |
| Contributing a change | [CONTRIBUTING.md](CONTRIBUTING.md) |

---

## What to include in a bug report

A report we can reproduce is fixed far faster than one we cannot:

1. `depkeeper --version` and `python --version`
2. The **smallest** requirements file that reproduces the behaviour
3. The exact command line
4. `depkeeper -vv <command> … 2> debug.log`, with `debug.log` attached
5. Expected versus actual behaviour
6. Your operating system, and whether depkeeper was installed with pip, pipx or from source

The Python version matters more than it usually would: depkeeper filters candidate versions
against the interpreter **it runs on**, so a version mismatch is a common cause of
"the recommendation looks wrong".

---

## Response expectations

depkeeper is maintained on a best-effort basis. There is no commercial support offering and no
service-level agreement.

| Request type | Typical handling |
|---|---|
| Security report | Acknowledged within 48 hours — see [SECURITY.md](SECURITY.md) |
| Bug report with a reproducer | Triaged first |
| Bug report without a reproducer | May be closed as not actionable after a request for detail |
| Feature request | Discussed before implementation; scope is deliberately narrow |
| Pull request | Reviewed as promptly as possible; ping the thread if it goes quiet |

---

## Version support

Only the latest `0.1.x` release is supported. Reproduce your issue on the current release before
reporting it.

depkeeper is alpha software: pin the version in automation, and read
[CHANGELOG.md](CHANGELOG.md) before upgrading. Recommendation logic is a behavioural contract, so
an upgrade can legitimately change an update plan.

---

## Out of scope

depkeeper is a narrow tool by design. These are not defects:

- It does not perform full transitive dependency resolution — `pip` does that.
- It does not query private package indexes.
- It does not scan for vulnerabilities — use `pip-audit` or `safety`.
- It does not propose major-version upgrades.
- It does not manage virtual environments or install packages.

See [Known limitations](https://rahulkaushal04.github.io/depkeeper/reference/limitations/) for the
full list, each with a workaround.
