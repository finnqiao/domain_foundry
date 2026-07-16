# hermes-agent adapter (P8)

Thin plugin that maps hermes-agent tools onto the `HarnessAPI` HTTP surface:

- `capture` / `query` / `correct` / `review_list` / `review_resolve` / `new_domain` / `wizard_reply`

Ships as `plugin.yaml` + `register(ctx)` and publishes via the
`hermes_agent.plugins` entry-point group. Implementation lands in phase P8.
