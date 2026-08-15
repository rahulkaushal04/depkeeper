---
title: Core Concepts
description: The model depkeeper uses — pipeline stages, invariants and design decisions
---

# Core Concepts

These pages describe *how depkeeper thinks*. They are the reference for anyone who needs to
predict, justify or debug a recommendation, and the prerequisite reading for contributors.

<div class="grid cards" markdown>

- :material-sitemap:{ .lg .middle } **[Architecture](architecture.md)**

    ---

    Module responsibilities, the request pipeline, and the design decisions behind them.

- :material-arrow-up-bold-box:{ .lg .middle } **[Version recommendation](version-recommendation.md)**

    ---

    How a single package's target version is chosen: boundaries, filters and inference.

- :material-vector-triangle:{ .lg .middle } **[Conflict resolution](conflict-resolution.md)**

    ---

    The iterative resolver, its strategies, its guarantees and its failure modes.

- :material-file-code:{ .lg .middle } **[Requirements parsing](requirements-parsing.md)**

    ---

    What the parser accepts, what it ignores, and what it cannot represent.

- :material-content-save-check:{ .lg .middle } **[Write safety](write-safety.md)**

    ---

    Atomic writes, multi-file rollback, encoding and line-ending preservation.

</div>

---

## The pipeline in one diagram

Both commands run the same five stages. `update` adds a sixth.

<figure>
<svg viewBox="0 0 1065 278" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="requirements.txt flows through RequirementsParser, PyPIDataStore, VersionChecker and DependencyAnalyzer, then forks to a Renderer that writes to stdout and a Writer that atomically rewrites requirements.txt">
<defs>
<marker id="pipeline-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker>
</defs>
<g font-family="var(--md-text-font-family, sans-serif)" fill="currentColor">
<rect x="40" y="40" width="122" height="48" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="101" y="60" text-anchor="middle" font-size="14">requirements</text>
<text x="101" y="77" text-anchor="middle" font-size="14">.txt</text>
<line x1="162" y1="64" x2="186" y2="64" stroke="currentColor" stroke-width="1.5" marker-end="url(#pipeline-arrow)"/>
<rect x="186" y="40" width="170" height="48" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="271" y="69" text-anchor="middle" font-size="14">RequirementsParser</text>
<line x1="356" y1="64" x2="380" y2="64" stroke="currentColor" stroke-width="1.5" marker-end="url(#pipeline-arrow)"/>
<rect x="380" y="40" width="130" height="48" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="445" y="69" text-anchor="middle" font-size="14">PyPIDataStore</text>
<line x1="510" y1="64" x2="534" y2="64" stroke="currentColor" stroke-width="1.5" marker-end="url(#pipeline-arrow)"/>
<rect x="534" y="40" width="138" height="48" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="603" y="69" text-anchor="middle" font-size="14">VersionChecker</text>
<line x1="672" y1="64" x2="696" y2="64" stroke="currentColor" stroke-width="1.5" marker-end="url(#pipeline-arrow)"/>
<rect x="696" y="40" width="170" height="48" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="781" y="69" text-anchor="middle" font-size="14">DependencyAnalyzer</text>
<path d="M 781 88 V 110 L 652 110 V 176" fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#pipeline-arrow)"/>
<path d="M 781 88 V 110 L 916 110 V 176" fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#pipeline-arrow)"/>
<rect x="537" y="178" width="230" height="60" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="652" y="202" text-anchor="middle" font-size="14">Renderer</text>
<text x="652" y="220" text-anchor="middle" font-size="11">table / simple / json → stdout</text>
<rect x="807" y="178" width="218" height="60" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
<text x="916" y="202" text-anchor="middle" font-size="14">Writer</text>
<text x="916" y="220" text-anchor="middle" font-size="11">atomic rewrite (update only)</text>
</g>
</svg>
<figcaption>Both commands share the first four stages; only <code>update</code> reaches the Writer.</figcaption>
</figure>

| Stage | Component | Responsibility |
|---|---|---|
| Parse | `RequirementsParser` | Text → `Requirement` objects, including `-r` / `-c` resolution. |
| Fetch | `PyPIDataStore` | One HTTP request per package per process; caching and coalescing. |
| Recommend | `VersionChecker` | Per-package target version under boundary, Python and constraint filters. |
| Resolve | `DependencyAnalyzer` | Cross-package consistency; mutates recommendations in place. |
| Render | `commands.check` | Table / simple / JSON, with stream separation. |
| Write | `commands.update` | Line-accurate, atomic, rollback-capable rewrite. |

---

## Non-negotiable invariants

These hold across the whole system. Contributors must not break them; operators can rely on them.

| # | Invariant | Enforced by |
|---|---|---|
| 1 | A recommendation never crosses a major version boundary when a current version is known. | `VersionChecker._build_package_from_data`, `DependencyAnalyzer` search helpers |
| 2 | A recommendation never violates the constraints declared in the file (unless `--pin`). | `VersionChecker._filter_by_constraints`, `_find_updates`, `Requirement.update_version` |
| 3 | A pre-release is never recommended. | `PyPIPackageData.get_python_compatible_versions` |
| 4 | `Package.recommended_version` equals `ResolutionResult.resolved_versions[name].resolved`. | `DependencyAnalyzer.resolve_and_annotate_conflicts` |
| 5 | Package names are compared only in PEP 503 canonical form. | `depkeeper.utils.naming.normalize_package_name` |
| 6 | `check` never writes to the filesystem. | No write path is imported by `commands.check` |
| 7 | A failed write leaves every affected file at its previous content. | `_commit_pending_writes` / `_rollback_writes` |
| 8 | Machine-readable formats never emit non-payload bytes on stdout. | `_status_stream_is_stderr` + per-stream consoles |

---

## Terminology

| Term | Definition |
|---|---|
| **Requirement** | One parsed line of a requirements file. |
| **Package** | A requirement enriched with PyPI metadata and version decisions. |
| **Current version** | The version inferred from the requirement's specifiers. |
| **Recommended version** | The version depkeeper would write. |
| **Retained specs** | The specifiers that survive a rewrite unchanged: upper bounds, exclusions, wildcard bands. |
| **Update set** | The resolver's working map of package name → proposed version. |
| **Live conflict** | A recorded conflict that the *final* update set still violates. |
| **Unavailable stub** | A `Package` created when PyPI metadata could not be fetched. |
