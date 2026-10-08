# Design discussion

**Why add a web dashboard?** It makes the core guarantees visible without typing a command for every
invocation. The dashboard calls the existing engines, displays the actual browser, and forwards manual
input under the same ownership lock and epoch. It does not replace UI automation with banking API
calls. A small presentation pause after each action makes replay observable without changing decisions.
One active run and bounded in-memory history keep this a local demonstration rather than a job platform.

**Is this a manual macro recorder?** No. Discovery asks the model to choose actions from current UI
observations. The resulting capability binds caller parameters and verifies outputs. Manual takeover
records redacted audit metadata, not a reusable macro; assisted discovery still withholds its artifact.

These questions connect the implementation to its trade-offs. The code and evidence, rather than
framework names, are the basis for discussing the submission.

**Why use a local application?** It makes exceptional states reproducible and avoids real customer
credentials. It also risks overfitting. The fixture therefore includes an iframe, non-semantic canvas
control, no test IDs, and injected runtime states. The runner's lack of direct access to fixture records
is a concrete boundary, but qualification against a second vendor surface remains future work.

**Why isn't a recording just a transcript?** A transcript is tied to one set of values and one model's
observations. A capability has a caller contract, explicit parameter references, independently checked
outputs, profile compatibility, and executable primitives without arbitrary code.

**How is discovery genuine if the app profile is predefined?** Permissions enumerate what actions are
allowed on each screen. They do not give their order. The model still chooses actions from actual live
observations and supplies typed bindings. Goal contracts define the required result. This is bounded
application onboarding, not unrestricted zero-configuration navigation of any unknown application.

**Why is replay deterministic if the UI is asynchronous?** Its decision rules and fallback order are
fixed. It waits for declared conditions rather than reproducing recorded timing. Changing business
state can legitimately produce a different outcome. Identical wall-clock time is not a guarantee.

**Why separate business outcomes from failures?** A member-not-found response is a valid answer for the
calling agent. A permission denial or broken target indicates an execution problem. Treating both as
an exception prevents the caller from choosing the right next step.

**Why not retry every failed click?** A timeout can occur after the server accepted a click. Repeating
it could duplicate a mutation. This slice permits only reversible preparation and blocks final commit.
Even so, uncertain dispatch requires intervention and revalidation rather than blind retry.

**What happens if the human advances farther than expected?** Resume is rejected until the declared
checkpoint is restored. Automatic reconciliation of arbitrary manual work is not safe to infer. A
future system could support a reviewed set of allowed resume checkpoints and action-specific proofs.

**Can a human click while automation owns the browser?** This local prototype cannot prevent a person
with OS access from touching the browser. Ownership gates all runner dispatch and records activity
while the human owns the session. A production worker would isolate the browser and expose input only
to the current authenticated lease holder. That stronger physical-control guarantee is not claimed here.

**Why does assisted discovery withhold the artifact?** The recorder knows the automation actions but
only safely records metadata about manual actions. Silently dropping manual work would create a
capability that cannot replay. Completing the goal and approving a reusable capability are different events.

**Can visual anchors generalize across tenants?** Only after qualifying the relevant theme/DPI/version.
Semantic targeting is preferred. The sample's static anchor contains no member data. Weak or duplicate
matches stop; replay never asks a model to guess a new location.

**Where is the production scaling seam?** A worker owns one isolated browser session. A registry selects
an approved artifact plus tenant profile. A queue dispatches invocations to workers; evidence storage
is partitioned by tenant. Worker concurrency and tenant authorization belong around the existing
execution core, not inside every action. None of that infrastructure is claimed as implemented.

**What does the live evidence establish?** Gemini completed one recorded discovery run in seven calls.
The generated artifact then replayed with different inputs and no model. Failed provider calls and
invalid proposals are also retained. This is inspectable evidence of the vertical slice, not a model
quality benchmark. The separate scripted planner/operator tests cover exceptional paths; the operator
evidence is not represented as a human demonstration. An optional personal handoff recording and
qualification against another vendor remain future work.
