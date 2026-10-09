# Six banking workflows

Harbor Ledger Bank is a fictional staff application. The automation prepares requests for review;
it does not open accounts, replace cards, resolve disputes, change addresses, send statements, or
waive fees. Its records and eligibility rules are synthetic examples, not a bank's production policy.

| Workflow | What the browser must do | What gets verified |
|---|---|---|
| Sub-account review | Find member, open the canvas-based account action, enter product and nickname | Member, product, nickname, ready-for-review status |
| Card replacement | Find member, choose Cards, locate the member's card, inspect its standing, prepare replacement preferences | Card reference, card product/standing, reason, delivery, review status |
| Transaction dispute | Find member, choose Disputes, locate a posted transaction, open dispute intake | Transaction reference, merchant/amount/status, dispute reason, contact channel, review status |
| Address change | Find member, open Contact maintenance, inspect current details, enter a new mailing address and verification route | Current contact information plus every requested address field and verification method |
| Statement request | Find member, open Documents, locate an eligible account, choose statement and delivery preferences | Account reference/product/access, statement period, format, delivery, review status |
| Fee adjustment | Find member, open Fee servicing, locate an assessed fee, prepare adjustment details | Fee reference/type/amount/standing, reason, requested resolution, supporting note, review status |

Card replacement, disputes, and contact maintenance are established servicing categories; see
[Bank of America's account-servicing overview](https://www.bankofamerica.com/credit-cards/credit-card-account-information-faq/)
and [dispute overview](https://www.bankofamerica.com/credit-cards/credit-card-disputes-faq/).
These sources motivate the examples; this demo does not implement or claim those institutions' policies.

## What makes this useful for the assignment?

The member screen exposes several departments. Discovery must choose the one that serves the goal,
navigate a record lookup where applicable, fill the right form, and recognize the verified review.
For example, a dispute requires finding a transaction; an address change needs contact maintenance.
The final contract also extracts values obtained from the UI, such as a transaction amount or fee standing.

The operator writes goal contracts, screen/control permissions, and bindings, not a production action
sequence for each new feature. `profiles/workflows.json` contains six goals and example inputs, with no
ordered steps. Genuine discovery creates the steps. Test-only scripted planners are explicitly labelled
and are never presented as AI-generated capabilities.

This does not make AI indispensable: a developer could script every workflow. The intended benefit is
discovering a supported UI path once and turning it into inspectable, deterministic automation. It is not
an autonomous financial decision system or a universal website agent. Address verification, dispute
adjudication, fee approval, and final submission remain outside the demonstrated automation.

## Discover and replay, entirely through the dashboard

1. Start `uv run capabilities web` using the root README setup, then open the dashboard on port 8766.
2. Choose a workflow card. The counter distinguishes six available goals from saved capabilities.
3. Choose **Discover with AI**, provider **Gemini**, and **Normal workflow**.
4. Click **Member 10023** under Example inputs. This fills every field with a coherent synthetic example.
5. Click **Discover and save**. Allow around 2–5 minutes because model requests are spaced apart.
6. Watch the actual browser in the preview and decisions in Activity. The model sees masked observations
   and a non-sensitive `input_applied` flag for fields already set on the current screen.
7. After success, inspect Result and Capability. Match the requested input values and review status.
8. Click **Use this capability with new inputs**, then **Member 10042**. The second example changes
   both the member and any member-owned record reference, plus other preferences.
9. Click **Run capability**. Expect success, the second example's outputs, and **zero model calls**.

No existing capability is required to start discovery. A new goal with no saved artifact automatically
opens discovery mode; replay remains unavailable until a valid capability exists. The bundled original
sub-account artifact is genuine live evidence. New artifacts remain local under `runs/web/` and appear
in the workflow's capability list after success. Creating another artifact for the same goal does not
create another business workflow. The live evidence index distinguishes genuine and fixture runs.

## Example records and negative tests

| Member | Card | Transaction | Statement account | Fee |
|---|---|---|---|---|
| 10023 | CARD-10023 | TXN-10023 | ACC-10023 | FEE-10023 |
| 10042 | CARD-10042 | TXN-10042 | ACC-10042 | FEE-10042 |
| 10077 | CARD-10077 | TXN-10077 | ACC-10077 | FEE-10077 |

Records are member-scoped. For example, member `10042` with `TXN-10023` returns `record_not_found`.
Appending `-HOLD` to a matching reference returns `request_not_eligible`: a pending transaction,
already pending replacement, restricted statement access, or already adjusted fee. These are deliberate
fixture states. Neither outcome produces a reusable capability or a success result.

Use member `99999` for `member_not_found`; `123` is rejected before execution. For an address change,
use two uppercase letters for State code and five digits for Postal code. A malformed address reaches
the application's validation outcome. The two provided statement periods are fixed fixture periods.

Every workflow supports the common member-search scenarios: expired session, known notice, unexpected
dialog, permission denial, slow loading, and application failure. Duplicate review controls and form
validation are tested at the relevant form. **Missing visual target** only applies to the sub-account
canvas action. During an expired session, Claim session, restore it in the live view, then Return to
automation. Early handback is rejected, and the same browser is retained.

## Tests and evidence

`tests/test_workflows.py` checks all six paths in real Chromium, discovery compilation with explicitly
scripted test planners, replay with a second member, no model initialization on replay, member-scoped
record isolation, ineligible records, parameter redaction, and address validation. Dashboard tests cover
discovering a goal with no previous artifact, selecting the resulting artifact, and replaying it through
the actual web controls. The test helpers never run in production discovery.

Run `make verify` for local checks and `make submission-check` for the original genuine-evidence gate.
Inspect the evidence index for which expanded workflows have also been exercised against a live model;
passing fixture tests is not proof of genuine model discovery.
