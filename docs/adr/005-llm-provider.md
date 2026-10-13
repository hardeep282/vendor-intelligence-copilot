# ADR-005: LLM provider -- direct Anthropic API, not Bedrock (for now)

Date: 2026-10-14 · Status: Accepted

## Decision
`copilot.llm.client.LLMClient` calls the Anthropic Messages API directly (`anthropic` Python SDK,
`anthropic==1.13.0`), not Claude via Amazon Bedrock.

## Why
- The sprint's Day 1-3 budget has no spare hours for a Bedrock IAM/model-access setup; the direct
  API needs only one key, matches ADR-004's key-lifecycle plan (dev in `.env`, prod in SSM) with
  no change, and every current doc/SDK fact in this file was verified live against the installed
  package, which is the direct SDK, not `boto3`'s Bedrock client.
- Production impact if this is reversed later: swap `LLMClient.__init__` to build a Bedrock
  client instead of `anthropic.Anthropic(...)`; the rest of `copilot.llm` (pricing, retries,
  repair loop, metrics) is provider-shaped, not Anthropic-API-shaped, except that the pricing
  table and the retryable-exception tuple would need Bedrock's own equivalents.

## A correction this decision carries (checked against the installed SDK and Anthropic's docs,
14 Oct 2026, superseding the sprint plan's assumption)
**`temperature`, `top_p` and `top_k` are not parameters of this model generation's Messages API.**
`anthropic.Anthropic(...).messages.stream()` / `.create()` do not accept them at all in SDK
1.13.0, and Anthropic's Sonnet 5.5 migration guide confirms a non-default value now returns a
400 ("Remove them"). The one per-call lever this generation exposes is `output_config.effort`
(`low`/`medium`/`high`/`xhigh`/`max`), which trades reasoning depth for latency/cost -- it is
not a temperature substitute (it does not change output diversity at a fixed token budget the
way temperature did).

**Consequence for the sprint plan:** B1 step 8, the "temperature lab" (sprint doc D3, item 8),
cannot be run as written -- there is no temperature to sweep on the models this project uses.
`copilot.llm.client.LLMClient.complete/structured` take an optional `effort` instead, and D3's
lab becomes an **effort lab**: the same question, `effort` swept across its five values instead
of temperature, same metrics (execution accuracy / grounding / output diversity / latency /
cost). The Tier-A interview concept ("why temperature 0 is not fully deterministic") stays valid
background knowledge -- it still applies to most other providers and to Claude models before this
generation -- but this project's own live measurement is now an effort/latency/cost trade-off,
not a temperature/diversity one. Flagged to the user in the Day 3 session that found it, rather
than silently building a lab that would fail against a 400 response.

## Consequences
- `copilot.llm.pricing.PRICES` holds direct-API USD/MTok prices, not Bedrock's.
- Day 9's offline QLoRA benchmark compares against this direct-API baseline.
- If Bedrock is adopted later (IAM-based access, no external key on the EC2 box, per the master
  prompt's Section 4), this ADR is superseded, not edited in place.
