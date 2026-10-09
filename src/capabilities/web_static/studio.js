"use strict";
const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="studio-csrf"]').content;
let mode = "replay",
  catalog = [],
  workflows = [],
  providers = {},
  current = null,
  activeId = null;
let imageUrl = null,
  lastFrame = -1,
  refreshing = false,
  starting = false;
const statusLabels = {
  starting: "Starting",
  running: "Running",
  success: "Success",
  business_outcome: "Outcome",
  failure: "Stopped",
};

async function api(path, body) {
  const response = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "X-Studio-CSRF": csrf,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      data.detail || "The dashboard could not complete that request.",
    );
  }
  return response.status === 204 ? null : response.json();
}
function error(message = "") {
  $("form-error").textContent = message;
}
function selected() {
  return catalog.find((c) => c.id === $("capability").value);
}
function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function isActive() {
  return current && ["starting", "running"].includes(current.status);
}
function providerStatus() {
  const ready = providers[$("provider").value];
  $("provider-status").textContent = ready
    ? "Key configured locally. Discovery uses API quota and may take 2–5 minutes."
    : "No local key configured. Replay remains available without a key.";
}
function setMode(next) {
  mode = next;
  $("replay-mode").classList.toggle("selected", mode === "replay");
  $("discover-mode").classList.toggle("selected", mode === "discover");
  $("replay-mode").setAttribute("aria-pressed", mode === "replay");
  $("discover-mode").setAttribute("aria-pressed", mode === "discover");
  $("discovery-fields").hidden = mode !== "discover";
  $("mode-description").textContent =
    mode === "replay"
      ? "Use a saved workflow with new inputs. No model or API key needed."
      : "AI starts from the goal and live screen. Verified success adds a new capability to the library.";
  $("start").textContent =
    mode === "replay" ? "▶  Run capability" : "✦  Discover and save";
  $("saved-capability-field").hidden = mode === "discover";
  $("capability").disabled = mode === "discover";
  renderArtifact();
  providerStatus();
}
function workflow() {
  return workflows.find((w) => w.id === $("workflow").value);
}
function canStart() {
  return (
    !isActive() &&
    !starting &&
    !!workflow() &&
    (mode === "discover" || !!selected())
  );
}
function renderLibrary() {
  $("library-count").textContent =
    `${workflows.length} workflows · ${catalog.length} saved capabilities`;
  $("workflow-cards").replaceChildren(
    ...workflows.map((w) => {
      const count = catalog.filter((c) => c.workflow_id === w.id).length;
      const button = element("button", undefined, "workflow-card");
      button.type = "button";
      button.classList.toggle("selected", w.id === workflow()?.id);
      button.setAttribute("aria-pressed", String(w.id === workflow()?.id));
      button.append(
        element("span", w.department, "eyebrow"),
        element("strong", w.title),
        element("span", w.description, "workflow-summary"),
        element(
          "span",
          count
            ? `${count} saved · ready to replay`
            : "Discover to create a capability",
          "workflow-badge",
        ),
      );
      button.addEventListener("click", () => {
        $("workflow").value = w.id;
        changeWorkflow();
      });
      return button;
    }),
  );
}
function renderInputs(example = null) {
  const w = workflow();
  if (!w) return;
  const values = example || w.examples[0];
  $("workflow-inputs").replaceChildren(
    ...Object.entries(w.contract.inputs).map(([name, spec]) => {
      const row = element("div", undefined, "workflow-input");
      const id = name === "member_id" ? "member-id" : name;
      const label = element("label", w.labels[name]);
      label.htmlFor = id;
      const input = element(spec.choices.length ? "select" : "input");
      input.id = id;
      input.name = name;
      input.required = true;
      if (spec.choices.length)
        input.replaceChildren(
          ...spec.choices.map((value) => element("option", value)),
        );
      else {
        input.maxLength = spec.max_length;
        input.autocomplete = "off";
      }
      if (spec.format === "member_id") {
        input.pattern = "[0-9]{5}";
        input.inputMode = "numeric";
        input.maxLength = 5;
      }
      input.value = values[name] || "";
      row.append(label, input);
      return row;
    }),
  );
}
function renderCapabilityOptions(preferId = null) {
  const previous = preferId || $("capability").value;
  const matches = catalog.filter((c) => c.workflow_id === workflow()?.id);
  $("capability").replaceChildren(
    ...matches.map((c) => {
      const label =
        c.provenance.run_id === "discover-2acef308bd9c"
          ? "Prepared sub-account review"
          : `${c.provenance.source === "llm_discovery" ? "AI discovery" : "Test fixture"} · ${c.provenance.run_id.slice(-6)}`;
      const option = element("option", label);
      option.value = c.id;
      return option;
    }),
  );
  if (matches.some((c) => c.id === previous)) $("capability").value = previous;
  if (!matches.length)
    $("capability").append(element("option", "No saved capability yet"));
  renderArtifact();
}
function changeWorkflow() {
  renderInputs();
  renderCapabilityOptions();
  if (!selected()) setMode("discover");
  renderLibrary();
}
async function loadCatalog(preferRunId = null) {
  const data = await api("/catalog");
  catalog = data.capabilities;
  workflows = data.workflows;
  providers = data.providers;
  const previousWorkflow = $("workflow").value;
  const created = catalog.find((c) => c.provenance.run_id === preferRunId);
  $("workflow").replaceChildren(
    ...workflows.map((w) => {
      const option = element("option", w.title);
      option.value = w.id;
      return option;
    }),
  );
  $("workflow").value =
    created?.workflow_id || previousWorkflow || workflows[0]?.id || "";
  if (
    !$("workflow-inputs").children.length ||
    $("workflow").value !== previousWorkflow
  )
    renderInputs();
  renderCapabilityOptions(created?.id);
  renderLibrary();
  $("sandbox-link").href = data.bank_origin;
  $("sandbox-link").title =
    "Opens an independent manual banking session. The engine's session is shown in the live view.";
  providerStatus();
}
function renderArtifact() {
  const cap = selected(),
    w = workflow();
  const visualOption = $("scenario").querySelector(
    'option[value="visual_missing"]',
  );
  visualOption.disabled = w?.id !== "subaccount";
  if (visualOption.disabled && $("scenario").value === "visual_missing")
    $("scenario").value = "normal";
  $("workflow-description").textContent = w?.description || "";
  $("goal-description").textContent = w?.goal || "";
  $("capability-meta").textContent =
    mode === "discover"
      ? "Goal and output checks only. AI chooses the action sequence."
      : cap
        ? `v${cap.version} · ${cap.steps} UI actions · ${cap.provenance.source === "llm_discovery" ? "AI-discovered" : "Test fixture"}`
        : "Discover this workflow first to enable replay.";
  $("artifact-json").textContent = cap
    ? JSON.stringify(cap.artifact, null, 2)
    : "No saved capability. A verified discovery will create one.";
  $("download-artifact").disabled = !cap;
  $("artifact-steps").replaceChildren(
    ...(cap?.artifact.steps || []).map((step, i) => {
      const row = element("div", undefined, "artifact-step");
      row.append(
        element("b", String(i + 1).padStart(2, "0")),
        element("span", `${step.action.op} · ${step.action.target.name}`),
      );
      if (step.action.value?.kind === "input")
        row.append(element("code", "{ " + step.action.value.name + " }"));
      return row;
    }),
  );
  $("start").disabled = !canStart();
}
function chooseTab(id) {
  document
    .querySelectorAll(".detail-tabs button")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.panel === id),
    );
  document
    .querySelectorAll(".detail-content")
    .forEach((panel) => (panel.hidden = panel.id !== id));
}
const names = {
  action_started: "Action",
  action_completed: "Action completed",
  checkpoint_verified: "Checkpoint verified",
  model_response: "Model response",
  decision: "AI decision",
  success_verified: "Outputs verified",
  artifact_saved: "Capability saved",
  replay_started: "Replay started · no model",
  discovery_started: "AI discovery started",
  condition_detected: "Condition detected",
  recovery_performed: "Automatic recovery",
  intervention_requested: "Human attention requested",
  control_transferred: "Control transferred",
  resume_requested: "Checking handback",
  resume_rejected: "Handback rejected",
  human_action: "Manual action",
  run_finished: "Run finished",
  evidence_captured: "Masked evidence saved",
  artifact_withheld: "Assisted run · capability withheld",
  navigation_blocked: "Navigation blocked",
  model_request_failed: "Provider request failed",
};
function renderEvents(events) {
  $("activity-empty").hidden = events.length > 0;
  $("events").replaceChildren(
    ...events
      .filter(
        (e) =>
          e.event !== "action_completed" && e.event !== "evidence_captured",
      )
      .slice(-60)
      .reverse()
      .map((e) => {
        const row = element("li");
        if (
          [
            "model_request_failed",
            "resume_rejected",
            "navigation_blocked",
          ].includes(e.event)
        )
          row.className = "error-event";
        row.append(
          element("span", undefined, "event-dot"),
          element(
            "span",
            new Date(e.at).toLocaleTimeString([], { hour12: false }),
            "event-time",
          ),
          element(
            "span",
            names[e.event] || e.event.replaceAll("_", " "),
            "event-label",
          ),
          element(
            "span",
            e.target || e.screen || e.code || e.owner || e.status || "",
            "event-detail",
          ),
        );
        return row;
      }),
  );
}
const reasons = {
  session_expired:
    "Claim the session, then click Restore session on the banking screen.",
  unexpected_dialog:
    "Claim the session, then acknowledge the notice on the banking screen.",
  resume_checkpoint_mismatch:
    "The required screen has not been restored. Claim again and resolve the interruption before returning control.",
  target_ambiguous:
    "More than one control matches. Inspect the page; do not guess. You can abort this demonstration.",
  visual_anchor_missing:
    "The expected visual control is missing. Inspect the page or abort this demonstration.",
};
function renderResult(result) {
  $("result-empty").hidden = !!result;
  $("result-content").hidden = !result;
  if (!result) return;
  $("result-title").textContent =
    result.status === "success"
      ? "Request ready for review"
      : result.status === "business_outcome"
        ? "Application returned a business outcome"
        : "Run stopped safely";
  $("result-message").textContent =
    result.status === "success"
      ? "The engine checked these values against the actual banking UI. No banking record was changed or request submitted."
      : (result.outcome || result.error?.code || "Unknown result").replaceAll(
          "_",
          " ",
        );
  $("outputs").replaceChildren(
    ...Object.entries(result.outputs).flatMap(([key, value]) => [
      element("dt", key.replaceAll("_", " ")),
      element("dd", String(value)),
    ]),
  );
  $("evidence-note").textContent =
    `Evidence: runs/web/${result.run_id} · persisted member details are redacted.`;
  $("use-discovered").hidden = !current?.artifact_available;
}
function renderState(state) {
  current = state;
  const owner = state.control.owner;
  const waiting = ["waiting", "human", "checking"].includes(owner);
  $("run-status").textContent = waiting
    ? owner === "human"
      ? "Your control"
      : owner === "checking"
        ? "Checking"
        : "Needs you"
    : statusLabels[state.status] || state.status;
  $("run-status").className = waiting
    ? "waiting"
    : state.status === "success"
      ? "good"
      : state.status === "failure"
        ? "bad"
        : "";
  $("action-count").textContent = state.completed_actions;
  $("model-count").textContent = state.model_calls;
  $("elapsed").textContent = state.elapsed_seconds.toFixed(1) + "s";
  $("screen-name").textContent = state.screen;
  $("live-status").textContent = isActive()
    ? "● Live session"
    : "Final session view";
  $("start").disabled = !canStart();
  $("stop").hidden = !isActive();
  $("takeover").hidden = !waiting;
  $("human-tools").hidden = owner !== "human";
  $("claim").hidden = owner !== "waiting";
  $("resume").hidden = owner !== "human";
  $("abort").disabled = owner === "checking";
  $("viewport").classList.toggle("human", owner === "human");
  $("takeover-title").textContent =
    owner === "human"
      ? "You have control of this browser"
      : owner === "checking"
        ? "Checking the restored session"
        : "Human attention needed";
  $("takeover-reason").textContent =
    reasons[state.control.reason] ||
    (state.control.reason || "").replaceAll("_", " ");
  renderEvents(state.events);
  renderResult(state.result);
}
async function preview(state) {
  if (state.frame === lastFrame) return;
  lastFrame = state.frame;
  const response = await fetch(`/api/runs/${state.id}/preview`, {
    headers: { "X-Studio-CSRF": csrf },
  });
  if (state.id !== activeId) return;
  if (response.status === 204) {
    $("browser-image").hidden = true;
    $("empty-state").hidden = false;
    $("empty-state").querySelector("h2").textContent =
      state.status === "starting"
        ? "Opening the banking session…"
        : "Preview temporarily unavailable";
    $("empty-state").querySelector("p").textContent =
      "The activity log shows the current run state. Unknown or unavailable screens are not displayed.";
    return;
  }
  if (!response.ok) return;
  const next = URL.createObjectURL(await response.blob());
  if (state.id !== activeId) {
    URL.revokeObjectURL(next);
    return;
  }
  $("browser-image").src = next;
  $("browser-image").hidden = false;
  $("empty-state").hidden = true;
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = next;
}
async function history() {
  const runs = await api("/runs");
  $("history-empty").hidden = runs.length > 0;
  $("history-list").replaceChildren(
    ...runs.map((run) => {
      const button = element("button", undefined, "history-row");
      button.append(
        element("span", run.id),
        element(
          "strong",
          `${run.workflow_title} · ${run.mode === "discover" ? "AI discovery" : "Replay"}`,
        ),
        element("span", statusLabels[run.status] || run.status),
      );
      button.disabled = isActive() && run.id !== activeId;
      button.addEventListener("click", async () => {
        activeId = run.id;
        lastFrame = -1;
        await refresh();
      });
      return button;
    }),
  );
  return runs;
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    if (activeId) {
      const id = activeId;
      const state = await api("/runs/" + id);
      if (id === activeId) {
        const finished =
          isActive() && !["starting", "running"].includes(state.status);
        renderState(state);
        await preview(state);
        if (finished) {
          await loadCatalog(state.artifact_available ? state.id : null);
          chooseTab("result-panel");
        }
      }
    }
    await history();
  } catch (e) {
    error(e.message);
  } finally {
    refreshing = false;
  }
}
$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (starting || isActive()) return;
  starting = true;
  activeId = null;
  current = null;
  $("run-status").textContent = "Starting";
  $("run-status").className = "";
  $("action-count").textContent = "0";
  $("model-count").textContent = "0";
  $("elapsed").textContent = "0.0s";
  $("browser-image").hidden = true;
  $("empty-state").hidden = false;
  $("empty-state").querySelector("h2").textContent =
    "Opening the banking session…";
  renderResult(null);
  renderEvents([]);
  $("start").disabled = true;
  error();
  try {
    const state = await api("/runs", {
      mode,
      workflow_id: workflow().id,
      ...(mode === "replay" ? { capability_id: selected().id } : {}),
      provider: $("provider").value,
      inputs: Object.fromEntries(new FormData($("run-form"))),
      scenario: $("scenario").value,
    });
    activeId = state.id;
    lastFrame = -1;
    renderState(state);
    chooseTab("activity-panel");
    await preview(state);
    await history();
  } catch (e) {
    error(e.message);
  } finally {
    starting = false;
    $("start").disabled = !canStart();
  }
});
async function command(path, body) {
  error();
  try {
    await api(`/runs/${activeId}/${path}`, body);
    await refresh();
  } catch (e) {
    error(e.message);
  }
}
$("stop").addEventListener("click", () => command("stop", {}));
$("use-discovered").addEventListener("click", async () => {
  await loadCatalog(activeId);
  setMode("replay");
  $("member-id").focus();
});
$("expand-view").addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.querySelector(".browser-panel").requestFullscreen();
  } catch {
    error(
      "Fullscreen is unavailable in this browser. You can widen the window instead.",
    );
  }
});
for (const name of ["claim", "resume", "abort"])
  $(name).addEventListener("click", () =>
    command("control/" + name, { epoch: current.control.epoch }),
  );
$("browser-image").addEventListener("click", (event) => {
  if (current?.control.owner !== "human") return;
  const rect = event.target.getBoundingClientRect();
  command("pointer", {
    epoch: current.control.epoch,
    x: Math.min(1279, ((event.clientX - rect.left) / rect.width) * 1280),
    y: Math.min(899, ((event.clientY - rect.top) / rect.height) * 900),
  });
});
$("type-text").addEventListener("click", () => {
  const text = $("manual-text").value;
  if (text) {
    command("text", { epoch: current.control.epoch, text });
    $("manual-text").value = "";
  }
});
document
  .querySelectorAll(".key")
  .forEach((button) =>
    button.addEventListener("click", () =>
      command("key", { epoch: current.control.epoch, key: button.dataset.key }),
    ),
  );
$("replay-mode").addEventListener("click", () => setMode("replay"));
$("discover-mode").addEventListener("click", () => setMode("discover"));
$("provider").addEventListener("change", providerStatus);
$("capability").addEventListener("change", renderArtifact);
$("workflow").addEventListener("change", changeWorkflow);
$("example-first").addEventListener("click", () =>
  renderInputs(workflow().examples[0]),
);
$("example-second").addEventListener("click", () =>
  renderInputs(workflow().examples[1]),
);
document
  .querySelectorAll(".detail-tabs button")
  .forEach((button) =>
    button.addEventListener("click", () => chooseTab(button.dataset.panel)),
  );
$("scenario").addEventListener("change", () => {
  $("scenario-help").textContent = [
    "session_expired",
    "unexpected_dialog",
  ].includes($("scenario").value)
    ? "The engine pauses. Claim the session, resolve the interruption in the live view, then return control."
    : "The run prepares a review. It does not submit requests or change banking records.";
});
$("download-artifact").addEventListener("click", () => {
  const cap = selected();
  if (!cap) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(cap.artifact, null, 2)], {
      type: "application/json",
    }),
  );
  const link = element("a");
  link.href = url;
  link.download = `${cap.workflow_id}.capability.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
(async () => {
  try {
    await loadCatalog();
    const runs = await history();
    activeId = runs[0]?.id || null;
    await refresh();
  } catch (e) {
    error(e.message);
  }
  setInterval(refresh, 800);
})();
