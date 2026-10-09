# Execution evidence

**Genuine discovery and model-free replay are complete.** Gemini operated the running application,
chose six UI actions plus a finish decision, and produced a verified capability in seven model calls.
That exact artifact replayed successfully with a different member, product, and nickname, using zero
model calls. Both runs used real Chromium against the synthetic application.

| Live evidence | What it establishes |
|---|---|
| [Live manifest](live/manifest.json) | Successful run, matching replay, usage, and retained failed attempts |
| [Generated capability](live/discover-2acef308bd9c/capability.json) | Parameterized artifact with `llm_discovery` provenance |
| [Discovery events](live/discover-2acef308bd9c/events.jsonl) | Seven provider response IDs, usage, actions, checkpoints, and verified success |
| [Replay events](live/replay-ac60b915dc4f/events.jsonl) | Matching artifact hash, independently verified success, zero model calls |
| [Replay result](live/replay-ac60b915dc4f/result.json) | Declared outputs, with sensitive values redacted |

The provider was explicitly selected as Gemini using the configured free-tier project. No paid-provider
fallback was enabled. Earlier failures include unavailable models, service timeouts, and policy-blocked
proposals; their original logs remain under `live/`. Failed runs never produced capabilities. The success
followed a schema improvement that constrains target descriptors to the current observed controls.
This supplies valid choices without telling the model their order.

## Offline regression evidence

An additional [web dashboard demonstration](web/manifest.json) records genuine Gemini discovery
initiated through the browser, followed by replay of that newly generated artifact with changed inputs:

- [Web discovery](web/web-discover-61c838849072/events.jsonl): seven genuine model calls, verified success.
- [Web-generated capability](web/web-discover-61c838849072/capability.json): reusable input references and provenance.
- [Matching web replay](web/web-replay-78a3a22a3f17/events.jsonl): changed member/product/nickname, zero model calls.

These web controls were operated by a computer-use assistant; they are not presented as a human
demonstration. The separate dashboard screenshot in `docs/screenshots/` intentionally displays synthetic
demo values as a presentation image. Engine evidence screenshots remain masked.

All recorded browser interactions below happened against the running synthetic application. The
planner and operator actors are explicitly scripted fixtures. The metadata does not claim they are
an LLM or a person. Replay uses no model client.

| Evidence | What it establishes |
|---|---|
| [Manifest](offline/manifest.json) | Actual outcomes, environment, elapsed times, and ten replay repetitions |
| [Compiled fixture capability](offline/fixture-discovery/capability.json) | Typed artifact emitted by the successful-run compiler; provenance is `test_fixture` |
| [Fixture discovery events](offline/fixture-discovery/events.jsonl) | Observe/act/compiler integration with a scripted planner |
| [Successful replay](offline/replay-success/events.jsonl) | Saved capability replayed for another member with zero model calls |
| [Not-found outcome](offline/replay-not-found/result.json) | Expected business outcome, not a crash |
| [Validation outcome](offline/replay-validation/result.json) | Explicit rejection of a submitted form |
| [Permission failure](offline/replay-permission-denied/result.json) | Authorization failure and masked screenshot evidence |
| [Slow load](offline/replay-slow/events.jsonl) | Bounded wait instead of timing-dependent replay |
| [Known notice](offline/replay-known-notice/events.jsonl) | Explicit, allowlisted recovery |
| [Expired-session handoff](offline/handoff-expired-session/events.jsonl) | Pause, claim, simulated manual restore, revalidate, resume the same page/context |
| [Unknown-dialog handoff](offline/handoff-unknown-dialog/events.jsonl) | Same protocol for an unexpected blocking condition |
| [Verification report](verification.json) | Local test, lint, typing, and installation checks |

Screenshots mask form values and member fields. Saved results retain safe product/status fields and
redact sensitive values. Raw extracted outputs are checked in tests and returned to the live caller;
they are not published as customer-like records. `checkpoint-*.png` images show the final UI, and
`failure-*.png` images show the state at intervention/failure.

The repeated-run result measures one pinned browser/fixture on one machine. Ten successful replays
are useful evidence of this demonstration, not a reliability guarantee for a bank or another vendor.

## Reproduction

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.browser-cache"
uv run python scripts/offline_evidence.py --out runs/reproduced-evidence --repetitions 10
```

The script starts its own sandbox on an ephemeral loopback port. It never reads an API key or calls
an external model. Choose a new output directory each time.

## Reproduce live evidence

Follow the genuine discovery commands in the root README. Store the run under `evidence/live/`,
then replay the **generated** artifact with new inputs into that same directory. Inspect the evidence
before committing it. Successful live discovery must include provider response IDs and usage,
policy-checked actions, a verified checkpoint, and a capability with `llm_discovery` provenance.

`make submission-check` rejects fixture-only discovery and requires a successful model-free replay
with the same canonical artifact hash. This is a consistency check, not cryptographic attestation of
provider logs. The source of each run remains part of the reviewer-visible evidence.

## Expanded banking workflows

All six goal paths pass real-browser compilation/replay tests with explicitly scripted test planners.
The current suite passes **109 tests**. In addition, [the expanded live manifest](expanded/manifest.json)
records a genuine Gemini transaction-dispute discovery (9 UI actions, 10 model calls), followed by
replay with a second member and transaction (9 actions, zero model calls). Its live browser run took
128.0 seconds; replay took 7.3 seconds, including web-preview presentation pauses.

Two separate genuine address-change attempts stopped on provider service-unavailable responses before
completion. Both failures are retained. They do not produce a capability and are not counted as verified
model discovery. Live evidence currently demonstrates two distinct goals: the original sub-account
review and the new transaction-dispute review. The other four goals are implemented and covered by
real-browser tests, but successful live model discovery is not claimed for them.

A newly built wheel was installed outside the checkout and replayed the dispute capability against
the local banking UI successfully with zero model calls. See [the workflow guide](../docs/BANKING_WORKFLOWS.md)
for example inputs, supported scenarios, and the exact discovery/replay procedure.
