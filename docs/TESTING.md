# Acceptance walkthrough

For the complete browser-based walkthrough, start with [WEB_DEMO.md](WEB_DEMO.md). The commands below
exercise the same engines through the CLI and remain useful for development and regression checks.

Run the setup and sandbox commands in the root README first. Leave the sandbox running in terminal A.
Use terminal B for the commands below. Replay and all automated tests need no model API key.

## 1. Inspect and run a capability

Open a `capability.json` under `evidence/live/discover-*/` whose provenance says `llm_discovery`.
Check that the artifact contains typed inputs, parameter references, declared outputs, before/after
checkpoints, and a model/run identifier. It should contain neither an API key nor recorded member values.
Use that exact path as `--artifact` in the README replay command.

Use a different member (`10042` or `10077`), `Checking`, and a new nickname. Expect `status: success`,
the requested outputs when `--show-outputs` is enabled, and `model_calls: 0`. The final screenshot should
show **Review sub-account** with sensitive fields masked. No account should be created.

For a slower visual walkthrough, add `--headed`. The browser closes when the run finishes; saved
screenshots and JSON events remain available in the evidence directory printed by the command.

## 2. Check results beyond the happy path

Repeat the same replay command, adding one scenario at a time:

| Change | Expected result |
|---|---|
| Use member `99999` | `business_outcome`, `member_not_found` |
| `--scenario validation` | `business_outcome`, `validation_error` |
| `--scenario slow` | Successful bounded waiting |
| `--scenario interstitial` | Successful replay with an explicitly allowed notice dismissal |
| `--scenario permission_denied` | Failure with a stable permission error and masked evidence |
| `--scenario app_error` | Failure with a stable application error |
| `--scenario ambiguous` | No guessed click; intervention required in headless mode |
| `--scenario visual_missing` | No guessed coordinates; intervention required in headless mode |
| `--scenario prompt_injection` | Ordinary successful review; page text cannot widen permissions |

Every run gets a new evidence directory. Inspect `result.json` for the terminal result and `events.jsonl`
for the action/checkpoint sequence. A business outcome is an expected answer, not an execution crash.

## 3. Take control of the live session

Add `--scenario session_expired --headed` to replay. Open the printed local operator URL. The browser
should pause at **Session expired**. Claim the session, click **Restore session** in the existing target
browser, then return control from the operator page. Expect the same window to continue to review.

Also try returning control before restoring the session. The runner should reject the handback and
remain paused. Repeat with `--scenario unexpected_dialog`, acknowledging the dialog during ownership.
The events should show ownership transfers and manual action metadata without recording entered values.

## 4. Verify the repository

```bash
make verify
make submission-check
```

The first command runs lint, formatting, strict typing, unit tests, real Chromium integration tests,
and offline deliverable checks. The second additionally requires genuine model discovery and a
successful zero-model replay tied to the same canonical capability hash. It does not call a model.

To regenerate independent offline evidence, use the README's `offline_evidence.py` command with a
new directory. The planner/operator in that script are explicitly test actors.

## 5. Optional new model discovery

Follow the Gemini commands in the root README only when you want a fresh live model run. Keep the
provider key in ignored `.env`. Quota or service failures produce a failed run and no capability;
they must not be described as successful discovery. A successful run has provider response IDs,
token usage, policy-checked actions, independently verified outputs, and a saved artifact. Replay
that new artifact with changed inputs to verify reuse.
