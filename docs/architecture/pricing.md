# Authoritative pricing

The backend owns cost accounting. SDK clients send `provider`, `model`, token
counts, and an automatic UTC `occurred_at`. The legacy `estimated_cost` field is
accepted for compatibility but ignored when authoritative values are persisted.

Pricing resolution uses a half-open effective window:

```text
effective_from <= occurred_at < effective_to
```

An open-ended row has no `effective_to`. Resolution first looks for an active
organization override and then for an active global default. Organization pricing
APIs expose global defaults plus the current organization's overrides, while only
the organization's own overrides can be created or changed through those APIs.
Overlapping active windows in the same organization scope are rejected.

The pricing service normalizes the provider with `strip + lowercase` and the model
with `strip`, performs all arithmetic with `Decimal`, and quantizes USD to eight
decimal places. It returns an explicit `PRICED` or `UNPRICED` result.

Every model call creates a `CostRecord`. A priced record snapshots the pricing row,
input and output rates, and the pricing effective timestamp. Editing a pricing row
later cannot change the recorded cost or its rate snapshots. An unpriced record has
no invented rate and carries `UNPRICED`; a configured zero-rate row carries
`PRICED` with a zero cost. Trace totals contain known authoritative cost and expose
`unpriced_model_calls` so partial cost coverage remains visible.

Seeded pricing rows are demo/default entries used to exercise the mechanism. They
are not synchronized with provider catalogs and do not guarantee live prices.

Migration `0008_authoritative_pricing` cannot establish provenance for costs that
older clients supplied before authoritative pricing existed. It marks those model
calls and records `UNPRICED`, clears their unverified cost values, and resets trace
cost aggregates while preserving calls, tokens, providers, models, and timestamps.
