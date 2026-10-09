# Computer-Use Automation System

## Architecture

Six supported workflows prepare sub-account, card replacement, dispute, address-change, statement,
and fee-adjustment reviews in a synthetic banking application. Final submissions remain blocked.
A separate FastAPI application supplies a legacy-style UI: an iframe, tables, ordinary form posts,
no test IDs, and a canvas action. The runner never imports its records or calls its business routes
outside browser interaction. Python keeps the provider adapter, contracts, executor, and tests cohesive.

`DiscoveryEngine` asks a vision-capable model for one typed action per live observation. `Executor`
retains policy authority, session ownership, and success verification. Only successfully executed
steps become a capability. `ReplayEngine` consumes that artifact without a provider dependency.
Both paths use the same `Surface` protocol. JSON files and sequential events are sufficient for this
single-session prototype; a queue or database would not strengthen the central guarantee.

`Capability Studio` adds a local web control plane over the same engines: parameter forms, capability
selection, genuine discovery, result inspection, a live browser preview, and run cancellation. One
command starts the console and sandbox on separate loopback origins. The console never calls banking
business routes on the runner's behalf; execution still uses the browser surface.

An independent goal registry supplies workflow-specific inputs, outputs, and examples without requiring
a prior capability. The member screen exposes multiple departments; discovery chooses the relevant path.
Record lookups enforce member ownership and distinguish missing from ineligible records. A non-sensitive
field-progress flag complements masked screenshots on longer forms.

The app profile deliberately contains control permissions and known state detectors, not an ordered
workflow. The goal contract defines the required result; it does not reveal the path. Discovery still
has to decide which control to use, bind the right parameter, and recognize when to finish. Gemini's
response schema enumerates current observed targets, preserving their types without prescribing order.
The recorded live run used seven model calls; its artifact replayed with new inputs and zero model calls.
Separate offline discovery evidence uses a labeled test double.

## Artifact schema

A capability has independent schema and capability versions, a vendor/profile identifier, typed input
parameters, declared output extraction, an ordered step list, success checks, and provenance. A step
contains a stable ID, before/after screen checkpoints, a typed action, a logical target, and a bounded
wait. Values are explicit `input` references or constants; this adapter permits input operations only
through the policy-approved parameter reference. It never executes artifact code or interpolated selectors.

Targets describe a control kind, visible name, and logical scope. `workspace` is mapped to an iframe by
this adapter, rather than storing browser objects or transcript references. Runtime business/recovery
rules belong to the versioned app profile; they are not inferred from a happy-path recording. An
exported JSON Schema and Pydantic validation make the contract inspectable by a caller or reviewer.
Unsupported profiles, extra executable fields, unknown versions, and undeclared references are rejected.

The compiler independently reads the final UI and compares member, product, nickname, and status
against the contract. A model's `finish` is only a request to verify. Manual assistance can finish a
goal, but suppresses automatic artifact publication until the complete path is rediscovered; an
unrecorded manual operation must not disappear from an unattended capability.

## Determinism & error handling

Replay follows fixed steps with parameter binding, exact scoped semantic matching, explicit navigation
waits, and before/after checkpoints. Duplicate matches are errors. The canvas control uses a static
image anchor, a bounded iframe search area, a high match threshold, and duplicate-match rejection.
Viewport, DPR, browser version, locale, and time zone are fixed. Visual matching supports this stable
fixture, not arbitrary DPI or appearance changes. Inputs and application state determine outputs;
determinism means fixed decisions and bounded declared recovery, not identical timing or bank data.

A missing member or rejected form is a typed business outcome. A known notice has one specific safe
dismissal rule; slow loads have bounded waits. Permission denial and app failure stop with stable error
codes. Unknown states, missing/ambiguous controls, and expired sessions request intervention. Timed-out
clicks are never automatically repeated: delivery might already have occurred. A human must restore the
pre-action checkpoint before a single retry of a permitted reversible step. Final mutations are blocked. Native browser prompts are cancelled and reported as hard failures;
HTML dialogs support live handoff.

Results separate success with declared outputs, a named business outcome, and failure with step,
expected/observed state, and an evidence reference. Logs never copy raw browser or provider exception
messages. Failure evidence is a masked screenshot, or a sanitized structural record when capture is
unsafe. Tests assert new parameter values, actual extracted results, failure classification, and zero
model initialization during replay. The evidence manifest reports observed repeated-run stability;
it is not a production reliability estimate.

## Heterogeneity & multi-tenant

The executor consumes `Surface` operations, not Playwright locators. A desktop implementation would map
logical scopes to windows, semantic targets to accessibility controls, and visual targets to qualified
screen anchors. It would implement the same observation, action, extraction, and checkpoint contracts.
The current browser adapter is qualified only for Harbor Ledger; it is not a universal desktop driver.

For many institutions, retain one vendor workflow and a versioned tenant profile containing origin,
logical-scope bindings, localized labels, visual anchors, and policy. Tenant overrides may specialize
targets but must not silently widen permissions or alter the output contract. Qualification would replay
a fixed acceptance suite against each vendor/version/profile combination, then approve that combination.
A mismatch should quarantine the profile and preserve the last qualified artifact rather than invoke
an LLM secretly during production replay. Session contexts, credentials, and evidence would be isolated
per tenant. Those registry, rollout, and isolation services are designed extension points, not implemented
multi-tenant infrastructure.

## Escalation & handoff

The control lifecycle is `automation → waiting → human → checking → automation`, or terminal closure.
An action lock ensures a control request cannot overtake an in-flight automation action. An incrementing
epoch rejects stale claims and resume requests. The local operator page carries run ID, step, stop
reason, and ownership. The operator uses the same browser page/context; no replacement login session
is created. Claims, manual click/edit/submit metadata, and control transfers share the run's event stream.

Returning control does not imply success. The runner waits for the expected screen and disappearance
of blocking conditions, then resumes. An invalid handback returns to `waiting`; timeout or abort closes
the run. The browser integration tests retain and compare the exact page/context objects across
handoff. Offline handoff evidence uses a clearly labeled scripted operator, exercising the real control
protocol and UI. The headed CLI supports an actual person through the same seam.
The web console also forwards pointer/keyboard input into the existing browser only under the human
ownership epoch. Its preview is the actual session; it never swaps in an independent banking iframe.

## Safety

Operator-owned policy enumerates origins, routes, control/action combinations, and parameter bindings.
Checks run before dispatch; browser routing enforces the network boundary, including redirects and
frames. Popups and WebSockets are blocked. Service workers are disabled. The account-creation route
is not permitted even during manual takeover. No model tool exposes a shell, arbitrary JavaScript,
HTTP client, or policy editing. Page notes and model output cannot authorize an action.

Sensitive input values stay in memory and are bound by the host. Model observations contain approved
control labels and masked screenshots. Artifacts use parameter references. Logs have an allowlisted
shape; persisted outputs redact sensitive fields. Screenshots mask form values and record data;
unknown screens withhold pixels. These are application-specific masks, not a generic PII detector.
The sample contains only synthetic data and makes no regulatory-compliance claim. Production requires
qualified masks, restricted model egress, retention controls, audited operator identity, and isolated
workers. The local console trusts the OS user, uses origin/CSRF checks, and has no enterprise login.
The web console's in-memory preview and caller outputs expose synthetic values locally; those pixels
are never sent to the model or saved as execution evidence. Unknown screens withhold the preview.

## Cuts

Implemented depth is concentrated on contracts, replay, error classification, and live-session ownership.
Desktop drivers, remote co-browsing, production authentication, distributed execution, artifact signing,
and automatic cross-tenant specialization are omitted. Crash recovery closes the live context rather
than pretending an in-memory session can be reconstructed. There is no autonomous LLM fallback on replay.

Repeated-run stability and multiple servicing workflows are demonstrated. The genuine discovery/replay evidence and
submission gate pass; 109 local tests cover the execution and control boundaries. Next steps are a
manual desktop handoff recording, vendor/profile qualification, and an approval registry. Live model evidence covers sub-account and dispute review; four other goals have only fixture-planner
browser validation. Two expanded address-discovery attempts stopped on provider unavailability.
Failures are retained; the successful runs are not a discovery reliability benchmark.
