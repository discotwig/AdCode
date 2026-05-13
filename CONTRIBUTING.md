# Contributing

AdCode is early infrastructure tooling. Contributions should improve operational safety, provider correctness, documentation clarity, or test coverage.

## Development Setup

```bash
pip install -r requirements.txt
pytest tests/
```

Integration tests require Meta credentials and are skipped when credentials are absent.

## Useful Contribution Areas

- Provider abstraction and Meta API coverage.
- State and drift correctness.
- Plan/apply safety, especially delete behavior and rename handling.
- Example stacks and realistic fixtures.
- Documentation for operators and agencies.
- Tests around edge cases in campaign, ad set, ad, and creative behavior.

## Engineering Expectations

- Keep stack isolation intact. A stack-scoped operation must not read or write another stack's `state.json`.
- Treat Facebook as the source for live actuals. Local state is what AdCode last pushed, not proof of what is currently live.
- Preserve the plan-before-apply workflow.
- Keep destructive operations explicit and reviewable.
- Add focused tests for behavior changes.
- Avoid unrelated refactors in feature or bugfix pull requests.

## Documentation Expectations

Use infrastructure terminology consistently:

- stack;
- desired state;
- state file;
- plan;
- apply;
- drift;
- provider.

Avoid positioning the project as a generic AI marketing tool. The AI integrations are helpers around a deterministic infrastructure engine.
