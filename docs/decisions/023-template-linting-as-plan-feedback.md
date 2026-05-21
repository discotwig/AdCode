# ADR-023: Template Linting as Plan Feedback

**Date:** 2026-05-20  
**Status:** Accepted  
**Builds on:** ADR-017, ADR-019, ADR-021, ADR-022  
**Related:** ADR-004, ADR-012, ADR-013, ADR-015

---

## Context

AdCode's recent direction makes two product commitments explicit:

1. The JSON stack template is a primary user interface.
2. The MCP tool surface should remain small and Terraform-like.

After ADR-022, the preferred operating loop is:

```text
edit JSON -> plan_stack -> fix JSON -> plan_stack -> apply_stack
```

This means `plan_stack` must provide excellent feedback. JSON Schema validation can prove that a template is structurally valid, but it cannot reliably answer whether a valid template is sensible, safe, complete, or likely to match the user's advertising intent.

Many high-value mistakes are not pure schema errors:

- placeholder Page IDs, image hashes, video IDs, URLs, or account IDs remain in a scaffold;
- a new campaign/ad set/ad is marked `ACTIVE` before review;
- no budget is declared at either campaign or ad set level;
- daily and lifetime budget fields are used in confusing combinations;
- a lifetime budget lacks start/end dates;
- objective, optimization goal, and billing event combinations look suspicious;
- creative is technically valid but lacks common review fields such as headline or CTA;
- a copied `fb_id` appears in what looks like a new draft;
- duplicate names or duplicate `fb_id` values may confuse correlation or review;
- targeting is technically valid but unusually broad, narrow, or incomplete.

These are exactly the kinds of issues that matter when users and AI assistants are expected to draft and edit JSON directly.

Adding many MCP endpoints to check each category would violate ADR-022. Instead, the simple tool surface should become smarter internally.

---

## Decision

AdCode will add deterministic template linting as a core feedback layer for stack templates.

Linting is distinct from JSON Schema validation and policy validation:

| Layer | Question | Typical result |
| --- | --- | --- |
| JSON Schema validation | Is the template structurally valid? | Blocking errors |
| Policy validation | Does the template violate business or governance rules? | Blocking errors or warnings |
| Template linting | Does this valid template look suspicious, incomplete, unsafe, or inconsistent? | Mostly non-blocking warnings |

Template linting should be deterministic, local, reproducible, and interface-independent. It should not require live Facebook API calls or AI review.

Lint findings should be surfaced through existing workflows, especially `plan_stack`, rather than through a new public MCP endpoint.

---

## Product Role

Template linting makes the simplified AdCode workflow viable.

If users are expected to edit JSON directly and use `plan_stack` as the main feedback path, then `plan_stack` should tell them not only whether the template is valid, but whether it deserves review before apply.

The product principle is:

> Schema validation says whether AdCode can parse the template. Linting says whether an experienced operator would pause and review it.

---

## Severity Model

The first version of linting should be conservative and mostly non-blocking.

Recommended severities:

- `info` — useful note or best-practice hint;
- `warning` — suspicious or incomplete configuration that should be reviewed;
- `error` — deterministic, high-confidence issue that should block apply.

Most initial rules should be warnings. Blocking behavior should remain primarily in schema validation, explicit policy rules, budget cap enforcement, and apply confirmation gates.

Individual lint warnings may later become policy rules if customer usage proves they should block mutation.

---

## Initial Rule Categories

The first implementation should prioritize high-signal, low-noise rules that support JSON-first authoring.

### Placeholder and scaffold cleanup

Detect placeholder values such as:

- `act_000000000`;
- `000000000000000`;
- `PAGE_ID`;
- `IMAGE_HASH`;
- `VIDEO_ID`;
- `TODO`;
- `TBD`;
- `example.com` or `https://example.com`.

These rules support scaffolded authoring and AI-generated drafts.

### Budget sanity

Warn about suspicious budget configuration, such as:

- no budget at campaign or ad set level;
- confusing combinations of campaign-level and ad-set-level budgets;
- both `daily_budget` and `lifetime_budget` on the same ad set;
- `lifetime_budget` without `start_time` and `end_time`;
- unusually low or high budgets when deterministic thresholds are available.

### Launch-status safety

Warn when new resources with no `fb_id` are marked `ACTIVE`. New drafted resources should often begin as `PAUSED` until review is complete.

### Objective, optimization, and billing hints

Add conservative compatibility warnings for high-confidence mismatches between campaign objective, ad set optimization goal, and billing event.

These should start as warnings unless the rule is deterministic and known to be invalid.

### Targeting review hints

Warn about targeting that may deserve review, such as missing age bounds, omitted placements, placeholder audience IDs, or unusually broad/narrow configuration.

Rules must avoid over-prescribing strategy; broad targeting can be intentional.

### Creative completeness

Warn about link or video creative that is valid but likely incomplete for review, such as missing headline, CTA, image hash, thumbnail, or final non-placeholder URL.

### `fb_id` hygiene

Detect high-risk correlation issues, such as duplicate `fb_id` values or `fb_id` values in scaffold-like new templates.

### Naming and duplicate hints

Warn about exact duplicate sibling names or obvious placeholder names such as `New Campaign`, `Test`, or `Copy of`.

Campaign names from Facebook, state files, or drift reports must still be displayed exactly as returned. Linting must not normalize, rewrite, or flag unusual-looking Unicode or character sequences as encoding problems.

---

## Integration Points

### `plan_stack`

`plan_stack` is the primary lint display surface. Its output should include a concise lint section before or near the changeset summary.

Findings should include:

- stable rule ID;
- severity;
- JSON path;
- message;
- suggested next action.

### `document_stack`

The campaign review packet should include lint findings in non-technical language, grouped as review notes or launch-readiness warnings.

### `draft_stack`

When `draft_stack` produces a starter template, it should run linting against the draft and return known assumptions, placeholders, ambiguities, and next edits.

### CLI, CI, and future hosted workflows

Linting should live in core services, not MCP-only code, so it can later support CI checks, PR review, durable plan records, hosted plan workflows, and audit/review artifacts.

---

## Implementation Direction

Add a dedicated linting service, likely `src/services/lint.py`.

Recommended structures:

- `LintFinding`
- `LintReport`
- `LintSeverity`
- `lint_stack(campaign_json) -> LintReport`

Each finding should include stable fields such as:

- `rule_id`;
- `severity`;
- `path`;
- `message`;
- `suggestion`;
- optional `docs_ref`.

Stable rule IDs are important for tests, documentation, suppression support, future CI, and possible policy promotion.

---

## Relationship to the Five Product Pillars

### Operational safety

Linting catches valid-but-risky templates before apply: active draft launches, placeholder IDs, missing budgets, duplicate IDs, and suspicious targeting or creative setup.

### Speed

Linting shortens the edit/plan/fix loop by surfacing likely mistakes early, especially for scaffolded or AI-generated templates.

### Governance

Linting encodes best-practice review expectations without turning every recommendation into a hard policy. High-value warnings can later graduate into policy rules.

### Explainability

Lint findings make plans and review packets easier to understand by explaining why a valid template may still deserve attention.

### Integration

A deterministic lint service can be reused by MCP, CLI, CI, PR checks, review packets, durable plans, and future hosted workflows without expanding the public tool surface.

---

## Non-Goals

This decision does not add a public `lint_stack` MCP tool.

This decision does not require live Facebook API calls.

This decision does not make linting AI-dependent.

This decision does not try to encode every Meta API compatibility rule in the first version.

This decision does not make all lint findings blocking.

This decision does not authorize broad account discovery through MCP.

---

## Consequences

### Positive

- The simplified MCP surface becomes more useful without adding endpoints.
- JSON-first authoring becomes safer and more approachable.
- `plan_stack` becomes a richer feedback path.
- AI-generated drafts can be checked deterministically.
- Review packets become more credible for non-technical users.
- Future CI and hosted workflows can reuse the same lint service.

### Negative

- Poorly tuned lint rules can create warning fatigue.
- Some rules may require careful wording to avoid over-prescribing marketing strategy.
- A deterministic linter will not catch every platform-specific or account-specific issue.
- Rule severity and suppression behavior will need thoughtful design as usage grows.

---

## Guiding Principle

Keep the MCP surface small, but make the main feedback loop smarter:

```text
JSON Schema validates structure.
Policies enforce rules.
Linting catches suspicious intent and launch-readiness issues.
plan_stack presents the combined feedback.
```
