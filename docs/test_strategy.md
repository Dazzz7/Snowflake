# Test Strategy

The test suite is intentionally small but targeted at the highest-risk failures:

- Natural-language interpretation should resolve common user terms to verified metric IDs.
- Geography normalization should map state names and abbreviations to FIPS codes without accidental word collisions.
- SQL validation should block mutating statements and wildcard selection.
- Non-additive metrics should not be summed into aggregate geographies.
- Golden tests should verify expected interpretations for common reviewer questions, with real answer checks running only when Snowflake credentials are configured.
- Ranking questions should work when the user asks the system to identify the geography.
- Follow-up ranking questions should reuse metric, year, geography level, and ranking operation.
- Composite metrics should generate SQL from their real source columns rather than a total-population shortcut.
- City aliases such as NYC should resolve before guardrails and use verified county-set filters.
- Ambiguous broad concepts such as income should clarify instead of silently choosing one metric.

With more time, I would add:

- Snowflake integration tests against a read-only test warehouse.
- Duplicate-grain validation before additive aggregation.
- Latency tests that fail over 60 seconds.
- Adversarial prompt tests for schema exfiltration and SQL injection.
- A larger golden set covering counties, ambiguous county names, unsupported forecasts, and no-data cases.
