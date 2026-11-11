# Support

Where to get help with depkeeper.

depkeeper is maintained on a best-effort basis. There is no paid support and no SLA.

---

## Try these first

1. [Troubleshooting guide](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/guides/troubleshooting.md)
2. [Known limitations](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/reference/limitations.md). Odd behaviour is often intended.
3. [FAQ](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/community/faq.md)
4. [Full documentation](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/index.md)
5. Debug output:

   ```bash
   depkeeper -vv check --format json > report.json 2> debug.log
   ```

   `debug.log` shows the file parsed, the settings in effect, HTTP retries and each decision.

---

## Where to ask

| You want to | Go to |
|---|---|
| Ask how something works | [Open a question issue](https://github.com/rahulkaushal04/depkeeper/issues/new?template=question.yml) |
| Report a bug | [Bug report](https://github.com/rahulkaushal04/depkeeper/issues/new?template=bug_report.yml) |
| Suggest a feature | [Feature request](https://github.com/rahulkaushal04/depkeeper/issues/new?template=feature_request.yml) |
| Report a security problem | [SECURITY.md](SECURITY.md). Never a public issue. |
| Report a Code of Conduct problem | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |
| Send a fix | [CONTRIBUTING.md](CONTRIBUTING.md) |

Not sure if it is a bug? Open a question issue. We can relabel it as a bug.

---

## What to include in a bug report

1. `depkeeper --version` and `python --version`
2. Your OS, and how you installed depkeeper (pip, pipx, source)
3. The smallest requirements file that shows the problem
4. The exact command
5. `debug.log` from `depkeeper -vv <command> 2> debug.log`
6. What you expected, and what happened

Python version matters. depkeeper filters versions for a target Python: `--python-version`, then config `python_version`, then the file's `requires-python`, then the Python it runs on.
A wrong-looking recommendation is often a version mismatch.

---

## Versions

Only the latest `1.x` release is supported. Try the newest release before you report.

Pin the version in automation and read [CHANGELOG.md](CHANGELOG.md) before upgrading. Recommendation logic is a behaviour contract, so an
upgrade can change an update plan.

---

## What depkeeper does not do

These are not bugs:

- Full transitive dependency resolution. `pip` does that.
- Vulnerability scanning. Use `pip-audit` or `safety`.
- Private index authentication.
- Major-version upgrades unless you opt in per package with `--allow-major` (they are otherwise reported as `major available`).
- Managing virtual environments or installing packages.

See [Known limitations](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/reference/limitations.md) for
workarounds.
