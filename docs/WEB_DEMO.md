# Five-minute web demonstration

After installing dependencies and Chromium using the root README, run:

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.browser-cache"
uv run capabilities web
```

Open **http://127.0.0.1:8766**. Keep the terminal running. It hosts the dashboard and a separate synthetic
banking application on port 8767. All following operations happen in the dashboard. No frontend build,
Node.js installation, model key, or external API is needed for replay and human takeover.

## 1. Replay for a member

Leave **Replay capability** selected. Choose **Prepared sub-account review**, member `10077`, product
`Checking`, nickname `Travel Fund`, and **Normal workflow**. Click **Run capability**.

Watch the actual banking browser search the member, open the form, enter the parameters, and reach
review. The local view refreshes periodically; it is not a recording or a simulated animation. The
expand button enlarges it. Expect **Success**, **6 UI actions**, and **0 model calls**. The Result tab
shows the values independently read from the banking UI. No account is created.

Change the member to `10042` and nickname to `Holiday Fund`. Run again. The same capability now produces
different verified outputs. There is no demonstration to record first, and no model is consulted.

## 2. Inspect what was saved

Open **Capability**. Read the action list and expand the JSON. Fields bind parameters such as
`member_id` and `nickname`; they do not contain the original member's values. The bundled capability
comes from the genuine recorded Gemini discovery. Downloading JSON exports this capability, not raw
browser history, cookies, or credentials.

## 3. Show a business outcome

Use member `99999` and run again. Expect **Outcome** and `member_not_found`, not success or an unhandled
exception. A malformed ID such as `123` is rejected before automation starts: this fixture uses exactly
five digits and has three demo members (`10023`, `10042`, `10077`). Arbitrary strings such as `XYZ` are
not valid IDs. Creating additional banking records is outside this demonstration's scope.

## 4. Take over without leaving the dashboard

Restore a valid member and select **Session expired · human takeover**. Start replay. At the pause:

1. Click **Claim session** above the banking view.
2. Click **Restore session** directly inside that view. The click goes into the existing engine-owned browser.
3. Click **Return to automation**. The runner validates the checkpoint and completes the request.

For a negative test, return control before restoring the session. The runner rejects that handback.
Claim again, restore the session, and return control. **Unexpected dialog** works similarly: acknowledge
the notice in the live view. While you own the session, the text box and keyboard buttons can operate
a focused field. They are disabled outside human ownership. **Stop current run** cancels the run and
closes its browser. It never reports cancellation as success.

Human takeover handles exceptions. It is not a manual workflow recorder. Manual action metadata is
audited, but a discovery run requiring manual assistance does not publish an unattended capability.

## 5. Let AI discover a fresh capability

With an eligible Gemini API key configured in local `.env`, choose **Discover with AI**, provider
**Gemini**, and **Normal workflow**. Enter a valid member, product, and nickname. Click **Discover and save**.

The model receives the goal contract and masked live observations. It does not receive the saved action
sequence or sensitive parameter values. Watch model calls and actual actions appear in Activity. Free-tier
requests are spaced out, so allow roughly 1–3 minutes. Provider errors or quota exhaustion stop visibly;
there is no paid fallback or automatic retry.

After success, use **Use this capability with new inputs**. Change the member and nickname and run replay.
Expect zero model calls. The newly generated capability also appears in the dropdown and remains
available after restarting the server because its JSON is stored under `runs/web/`.

## What belongs to which session?

The embedded live view is the engine's actual banking session. **Open manual sandbox** opens a separate
session for exploring the sample application yourself. Manually clicking there does not train the model,
record a capability, or control an active run. A banking employee would normally submit inputs through
this control panel or a calling application; the automation then prepares the review in its own session.
Embedding the automation into a production banking application's login and session lifecycle would
require a separate integration, which is not claimed here.

## Checks and limits

`make verify` includes web API tests and a real browser test of the dashboard controls, replay, and
takeover. `make submission-check` verifies the checked-in genuine discovery/replay evidence. See
[TESTING.md](TESTING.md) for the full scenario matrix and CLI equivalents.

Only one run executes at a time. Recent runs retain the latest 20 views in memory; restarting clears
those views but preserves capability files and masked evidence. Successful runs close the real browser
and keep its final frame visible. Local operator previews and returned outputs show synthetic values;
persisted evidence and model observations remain redacted. The console is loopback-only and intended
for a trusted local OS user, not public hosting. Stop it with Ctrl+C. If a port is occupied, close the
previous instance or specify `--port 8776 --bank-port 8777`.
