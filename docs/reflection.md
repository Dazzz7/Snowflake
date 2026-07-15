# Reflection

## Development Process

I started from the assignment requirements and optimized for a reliable, defensible slice rather than broad but fragile text-to-SQL. The core architecture separates language interpretation from data authority: deterministic parsing and an optional hosted LLM adapter help interpret language, while application code verifies metrics, geographies, SQL, and results.

The most important decision was to create a verified metric registry. Census datasets contain many similarly named variables with different universes, so letting a model choose columns directly is risky. The registry makes `total_population` resolve to `B01003e1` and prevents accidental use of a different population universe.

## Key Tradeoffs

I focused first on state-level metrics and safe SQL. That means the app can answer a smaller set of questions reliably and refuse others clearly. For example, median household income is present in the registry, but the response labels the current block-group median aggregation as a proxy unless a state-grain source is configured.

The current system uses deterministic SQL templates instead of arbitrary generated SQL. This limits flexibility, but it greatly improves correctness, validation, and reviewability under the 24-hour constraint.

I also changed the completeness rule after testing ranking questions. A missing named geography is not automatically incomplete. For questions like "Which state has higher population in USA?", the geography level is state, the scope is all states, and the operation is a descending ranking.

The next architectural improvement was to move beyond one-column population handling. Metrics now support direct columns, composite count expressions, and distribution expressions. For example, population age 65 and older is defined as a sum of verified B01001 age columns, and age distribution traces show all age-band source columns rather than pretending the answer came from total population.

## Edge Cases

Handled:

- Off-topic or unsafe requests.
- Missing metric or missing geography.
- Follow-up questions like "What about Texas?"
- Ranking follow-ups like "What is second?" and "Show me top 5."
- Threshold questions such as "states above 10 million people."
- Age breakdown for a selected state.
- Population age 65+ as a composite metric.
- NYC as a verified city alias backed by five borough county FIPS codes.
- Ambiguous income wording as a clarification.
- Taxonomy-backed capability responses.
- Non-additive metric aggregation.
- Mutating SQL and wildcard SQL.
- Empty, null, negative, or implausible results.
- Unsupported future forecasts.

Partially handled:

- Comparison and ranking are supported for additive state-level metrics.
- County names are not fully supported yet, because duplicate county names require a stronger resolver.
- Schema discovery scripts exist, but production should use their output to continuously validate the registry.

## What I Would Improve

With more time, I would add broader county and tract support, discover the best available table grain automatically, and prefer state-level tables over block-group aggregation when available. I would also add a duplicate-grain preflight query before summing, broaden the verified metric set, persist sessions outside the process, and run deployed end-to-end tests against the final public URL.

## Testing Approach

The tests target the most dangerous failure modes: wrong metric selection, wrong geography normalization, unsafe SQL, invalid aggregation, and common golden questions. I would expand this into a 25-40 case golden suite with direct, comparison, ranking, follow-up, ambiguous, unsupported, adversarial, misspelled, and no-data examples.
