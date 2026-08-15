---
title: License
description: depkeeper is distributed under the Apache License 2.0
---

# License

depkeeper is distributed under the **Apache License, Version 2.0**.

The authoritative text is
[`LICENSE`](https://github.com/rahulkaushal04/depkeeper/blob/main/LICENSE) in the repository, and
the canonical version is published at
[apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0).

```text
Copyright 2024-2026 Rahul Kaushal

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

## Summary

This summary is informational. The licence text governs.

| You may | Conditions | Not granted |
|---|---|---|
| Use commercially | Include the licence and copyright notice | Trademark rights |
| Modify | State significant changes | Warranty |
| Distribute | Retain notices in redistributed source | Liability protection for you as redistributor |
| Sublicense | | |
| Use privately | | |
| Use patents granted by contributors | Patent grant terminates if you initiate patent litigation over the work | |

---

## Using depkeeper in a commercial product

Permitted. When redistributing depkeeper — modified or not — include:

1. A copy of the Apache License 2.0.
2. The original copyright notice.
3. A `NOTICE` file if one is present in the distribution.
4. A statement of any significant modifications you made.

Using depkeeper as a development tool, without redistributing it, imposes no obligations.

---

## Contributions

Contributions are licensed under the same terms, per section 5 of the licence: a contribution
intentionally submitted for inclusion is licensed to the project under Apache-2.0 without
additional terms, unless you state otherwise explicitly.

---

## Third-party licences

depkeeper's runtime dependencies carry their own licences:

| Dependency | Licence |
|---|---|
| `click` | BSD-3-Clause |
| `packaging` | Apache-2.0 / BSD-2-Clause (dual) |
| `httpx` | BSD-3-Clause |
| `rich` | MIT |
| `tomli` | MIT |

Verify the licence of the exact version you ship:

```bash
pip install pip-licenses
pip-licenses --packages click packaging httpx rich tomli
```
