"""Surface-neutral interface plus one browser implementation.

Selectors stay inside the adapter. Flow execution knows only actions and checks.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Literal, Protocol

import cv2
import numpy as np
from playwright.async_api import (
    Browser,
    BrowserContext,
    Dialog,
    FrameLocator,
    Locator,
    Page,
    Playwright,
    Request,
    Route,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeout,
)

from capabilities.contracts import Action, Click, Fill, Select, Target, resolve
from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence, atomic_write
from capabilities.policy import Policy
from capabilities.session import SessionController

SCREENS = (
    "Find a member",
    "Member details",
    "Prepare sub-account",
    "Review sub-account",
    "Member not found",
    "Validation error",
    "Permission denied",
    "Application unavailable",
    "Session expired",
    "Service record not found",
    "Request not eligible",
    "Card services",
    "Card details",
    "Replacement preferences",
    "Review card replacement",
    "Transaction disputes",
    "Transaction details",
    "Dispute details",
    "Review transaction dispute",
    "Contact details",
    "New mailing address",
    "Review address change",
    "Statements and documents",
    "Statement account",
    "Statement preferences",
    "Review statement request",
    "Fee servicing",
    "Fee details",
    "Adjustment details",
    "Review fee adjustment",
)
INSTRUMENTATION = """(() => {
  for (const kind of ['click', 'input', 'change', 'submit']) {
    document.addEventListener(kind, event => {
      const t = event.target;
      const tag = ['BUTTON','INPUT','SELECT','A','CANVAS','FORM'].includes(t?.tagName) ? t.tagName : 'OTHER';
      const allowed = ["Restore session", "Acknowledge notice", "Dismiss notice", "Member ID", "Nickname", "Product"];
      const label = (t?.innerText || t?.labels?.[0]?.innerText || "").trim();
      const control = allowed.includes(label) ? label : "unclassified";
      window.recordManual({kind, tag, control}).catch(() => {});
    }, true);
  }
})();"""


class Surface(Protocol):
    async def screen(self) -> str: ...
    async def execute(self, action: Action, inputs: dict[str, str]) -> None: ...
    async def read(self, target: Target) -> str: ...
    async def wait_screen(
        self, expected: str, timeout_ms: int = 3000, allow_exceptional: bool = True
    ) -> None: ...
    async def condition(self) -> str | None: ...
    async def recover_notice(self) -> None: ...
    async def observation(self) -> dict[str, Any]: ...
    async def failure_evidence(self) -> str: ...


class BrowserSurface:
    def __init__(
        self,
        policy: Policy,
        evidence: Evidence,
        control: SessionController,
        headless: bool = True,
        channel: str | None = None,
    ):
        self.policy, self.evidence, self.control = policy, evidence, control
        self.headless, self.channel = headless, channel
        self.runtime: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page
        self.blocked = False
        self.dialog: Dialog | None = None
        self.applied_inputs: set[str] = set()

    async def start(self, url: str) -> None:
        self.policy.check_url(url)
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(
            headless=self.headless, channel=self.channel
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=1,
            locale="en-US",
            timezone_id="UTC",
            service_workers="block",
            accept_downloads=False,
        )
        self.context.set_default_timeout(3000)
        await self.context.route("**/*", self._route)
        await self.context.route_web_socket("**/*", self._websocket)
        await self.context.expose_binding("recordManual", self._manual_binding)
        await self.context.add_init_script(INSTRUMENTATION)
        self.page = await self.context.new_page()
        self.context.on("page", self._popup)
        self.page.on("dialog", self._on_dialog)
        self.page.on("download", lambda _: setattr(self, "blocked", True))
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.wait_screen("Find a member")

    async def _route(self, route: Route, request: Request) -> None:
        if not self.policy.allows_url(request.url):
            self.blocked = True
            self.evidence.event("navigation_blocked", code="off_allowlist")
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _websocket(self, socket: WebSocketRoute) -> None:
        self.blocked = True
        self.evidence.event("navigation_blocked", code="websocket_not_supported")
        await socket.close()

    async def _popup(self, page: Page) -> None:
        self.blocked = True
        await page.close()

    async def _on_dialog(self, dialog: Dialog) -> None:
        self.dialog = dialog
        await dialog.dismiss()
        self.evidence.event("native_dialog_cancelled", code=dialog.type)

    async def _manual_binding(self, source: dict[str, Any], payload: dict[str, object]) -> None:
        if self.control.owner == "human":
            self.applied_inputs.clear()
        if self.policy.allows_url(source["frame"].url):
            await self.control.record_manual(payload)

    @property
    def workspace(self) -> FrameLocator:
        return self.page.frame_locator('iframe[title="Workspace"]')

    async def _check_context(self) -> None:
        if self.blocked:
            raise ExecutionError("navigation_blocked")
        self.policy.check_url(self.page.url)
        for frame in self.page.frames:
            if frame.url not in {"", "about:blank"}:
                self.policy.check_url(frame.url)

    def _locator(self, target: Target) -> Locator:
        if target.scope not in {"workspace", "root"}:
            raise ExecutionError("unsupported_scope")
        scope: FrameLocator | Page = self.workspace if target.scope == "workspace" else self.page
        if target.kind == "label":
            return scope.get_by_label(target.name, exact=True)
        if target.kind == "button":
            return scope.get_by_role("button", name=target.name, exact=True)
        if target.kind == "link":
            return scope.get_by_role("link", name=target.name, exact=True)
        if target.kind == "field":
            return (
                scope.locator("table.data tr")
                .filter(has=scope.get_by_text(target.name, exact=True))
                .locator(":scope > td:nth-child(2)")
            )
        if target.kind == "text":
            return scope.get_by_text(target.name, exact=True)
        raise ExecutionError("unsupported_target")

    async def _unique(self, locator: Locator) -> Locator:
        try:
            await locator.first.wait_for(state="visible")
        except PlaywrightTimeout as error:
            raise ExecutionError("target_missing") from error
        if await locator.count() != 1:
            raise ExecutionError("target_ambiguous")
        return locator

    async def screen(self) -> str:
        await self._check_context()
        if self.dialog:
            return "native_dialog"
        heading = self.workspace.locator("h1")
        if await heading.count() != 1:
            return "unknown"
        value = (await heading.inner_text()).strip()
        return value if value in SCREENS else "unknown"

    async def wait_screen(
        self, expected: str, timeout_ms: int = 3000, allow_exceptional: bool = True
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        observed = "unknown"
        while asyncio.get_running_loop().time() < deadline:
            observed = await self.screen()
            if observed == expected:
                return
            if allow_exceptional and observed in {
                "Member not found",
                "Validation error",
                "Permission denied",
                "Application unavailable",
                "Session expired",
                "Service record not found",
                "Request not eligible",
                "native_dialog",
            }:
                return  # The engine classifies exceptional states before checking the checkpoint.
            await asyncio.sleep(0.05)
        raise ExecutionError("checkpoint_mismatch", expected=expected, observed=observed)

    async def condition(self) -> str | None:
        screen = await self.screen()
        mapping = {
            "Member not found": "member_not_found",
            "Service record not found": "record_not_found",
            "Request not eligible": "request_not_eligible",
            "Validation error": "validation_error",
            "Permission denied": "permission_denied",
            "Application unavailable": "app_unavailable",
            "Session expired": "session_expired",
            "native_dialog": "native_dialog_cancelled",
            "unknown": "unknown_screen",
        }
        if screen in mapping:
            return mapping[screen]
        if await self.workspace.get_by_role(
            "dialog", name="Known service notice", exact=True
        ).count():
            return "known_notice"
        if await self.workspace.get_by_role("dialog").count():
            return "unknown_dialog"
        return None

    async def recover_notice(self) -> None:
        # This exact non-mutating dismissal is the profile's only automatic recovery click.
        dialog = self.workspace.get_by_role("dialog", name="Known service notice", exact=True)
        async with self.page.expect_event(
            "framenavigated", predicate=lambda frame: frame.parent_frame == self.page.main_frame
        ):
            await (
                await self._unique(dialog.get_by_role("button", name="Dismiss notice", exact=True))
            ).click()
        await self.wait_screen("Member details")

    async def execute(self, action: Action, inputs: dict[str, str]) -> None:
        await self._check_context()
        try:
            if action.target.kind == "visual":
                if not isinstance(action, Click):
                    raise ExecutionError("unsupported_action")
                await self._visual_click(action.target)
                self.applied_inputs.clear()
            else:
                locator = await self._unique(self._locator(action.target))
                if isinstance(action, Click):
                    async with self.page.expect_event(
                        "framenavigated",
                        predicate=lambda frame: frame.parent_frame == self.page.main_frame,
                    ):
                        await locator.click()
                    await self.workspace.locator("h1").wait_for(state="visible")
                    self.applied_inputs.clear()
                elif isinstance(action, Fill):
                    await locator.fill(resolve(action.value, inputs))
                    if action.value.kind == "input":
                        self.applied_inputs.add(action.value.name)
                elif isinstance(action, Select):
                    await locator.select_option(label=resolve(action.value, inputs))
                    if action.value.kind == "input":
                        self.applied_inputs.add(action.value.name)
            await self._check_context()
        except PlaywrightTimeout as error:
            if self.dialog is not None:
                raise ExecutionError("native_dialog_cancelled") from error
            # A timed-out click may already have been delivered. The caller must not retry it blindly.
            raise ExecutionError("action_timeout") from error

    async def _visual_click(self, target: Target) -> None:
        if target.name != "New sub-account":
            raise ExecutionError("visual_anchor_unknown")
        # Image itself is static, non-sensitive UI chrome. Browser viewport/DPR are pinned.
        template = cv2.imread(str(Path(__file__).parent / "anchors/new-subaccount.png"))
        iframe = self.page.locator('iframe[title="Workspace"]')
        box = await iframe.bounding_box()
        if box is None:
            raise ExecutionError("visual_anchor_missing")
        screenshot = await iframe.screenshot()  # Memory only; never write unmasked pixels.
        pixels = cv2.imdecode(np.frombuffer(screenshot, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None or template is None or min(pixels.shape[:2]) < min(template.shape[:2]):
            raise ExecutionError("visual_anchor_missing")
        response = cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(response)
        if score < 0.985:
            raise ExecutionError("visual_anchor_missing")
        x, y = location
        height, width = template.shape[:2]
        # Suppress the same match's neighborhood; reject a second plausible target.
        response[max(0, y - height) : y + height, max(0, x - width) : x + width] = -1
        if float(response.max()) >= 0.985:
            raise ExecutionError("visual_anchor_ambiguous")
        async with self.page.expect_event(
            "framenavigated", predicate=lambda frame: frame.parent_frame == self.page.main_frame
        ):
            await self.page.mouse.click(box["x"] + x + width / 2, box["y"] + y + height / 2)
        await self.workspace.locator("h1").wait_for(state="visible")

    async def read(self, target: Target) -> str:
        await self._check_context()
        return (await (await self._unique(self._locator(target))).inner_text()).strip()

    async def observation(self) -> dict[str, Any]:
        screen = await self.screen()
        # Only profile-known UI labels go to the model; record values remain opaque.
        controls = []
        for rule in self.policy.actions:
            if rule.screen == screen:
                target = Target(kind=rule.kind, name=rule.name)  # type: ignore[arg-type]
                if target.kind == "visual" or await self._locator(target).count():
                    controls.append(
                        {
                            "op": rule.op,
                            "target": target.model_dump(),
                            "input": rule.input_name,
                            "input_applied": rule.input_name in self.applied_inputs,
                        }
                    )
        result: dict[str, Any] = {"screen": screen, "controls": controls}
        if screen in SCREENS:
            result["image_base64"] = base64.b64encode(await self._masked_image()).decode()
        return result

    async def _masked_image(self) -> bytes:
        masks = [
            self.workspace.locator("input, select, textarea"),
            self.workspace.locator("table.data td:not(:first-child)"),
            self.workspace.locator(".service-context, .record-hint"),
        ]
        # Unknown screens are never captured. Known profile masks include visible financial data.
        return await self.page.screenshot(mask=masks, mask_color="#253746", animations="disabled")

    async def failure_evidence(self) -> str:
        return await self.capture("failure")

    async def capture(self, kind: Literal["failure", "checkpoint"] = "checkpoint") -> str:
        name = f"{kind}-{self.evidence.sequence:04d}"
        screen = "unavailable"
        try:
            screen = await self.screen()
            if screen in SCREENS and not self.dialog:
                path = self.evidence.root / f"{name}.png"
                path.write_bytes(await self._masked_image())
                self.evidence.event("evidence_captured", evidence=path.name)
                return path.name
        except Exception:
            pass  # Capture must never replace the original failure or leak a browser exception.
        path = self.evidence.root / f"{name}.json"
        atomic_write(
            path,
            json.dumps(
                {
                    "screen": screen,
                    "owner": self.control.owner,
                    "capture": "sanitized structural state; pixels withheld",
                }
            ),
        )
        self.evidence.event("evidence_captured", evidence=path.name)
        return path.name

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.runtime:
            await self.runtime.stop()
