# Contributing to domain_expert

Thanks for helping build the structured-life data layer for agent runtimes.

## Development setup

```bash
cd domain_expert
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Optional app shell (Node only needed to rebuild static assets):

```bash
cd app && npm install && npm run build
```

## Principles

1. **Capture first** — raw provenance reaches the ledger before interpretation.
2. **Never drop** — ambiguity becomes review / unfiled / ledger-only, never silence.
3. **Packs are data** — Domain Packs ship YAML + generated SQL, not arbitrary Python.
4. **No personal data** — fixtures must come from `examples/synthetic/` only.
5. **Invariant tests** — prefer contract assertions over live-count / wall-clock fixtures.
6. **Frozen clock in evals** — never call `datetime.now()` outside the clock provider.

## Pack authoring style guide (seed)

- Prefer singular object type names (`bake`, not `bakes`).
- Declare `unit` on every numeric field that has one; never assume.
- Prefer enums with `allow_other: true` over open free-text for categorical fields.
- Distinguish events (timestamped occurrences) from regimens (ongoing rules).
- Ship ≥8 routing examples and ≥2 negative examples; `pack validate` enforces this.
- Cross-domain facts use explicit `links`, never a merged universal schema.

## Pull requests

- Keep PRs focused; one concern per PR when practical.
- Run `ruff check`, `pyright`, and `pytest` before requesting review.
- Do not add `*.sqlite`, binary blobs, or real PII to the tree.
- New routing behavior should add eval fixtures (cassette-backed).

## License

By contributing, you agree your contributions are licensed under the MIT License.
