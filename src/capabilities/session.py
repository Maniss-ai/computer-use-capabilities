"""Single-writer control transfer for one live browser. No second browser is created."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from capabilities.errors import ExecutionError
from capabilities.evidence import Evidence

Owner = Literal["automation", "waiting", "human", "checking", "closed"]


class SessionController:
    def __init__(self, evidence: Evidence, timeout: int = 300, interactive: bool = False):
        self.evidence = evidence
        self.timeout = timeout
        self.interactive = interactive
        self.owner: Owner = "automation"
        self.epoch = 0
        self.interventions = 0
        self.reason: str | None = None
        self.step: str | None = None
        self.lock = asyncio.Lock()
        self.resumed = asyncio.Event()
        self.cancelled = False

    def state(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "epoch": self.epoch,
            "reason": self.reason,
            "step": self.step,
            "run_id": self.evidence.run_id,
            "interventions": self.interventions,
        }

    @asynccontextmanager
    async def automation(self) -> AsyncIterator[None]:
        async with self.lock:
            if self.owner != "automation":
                raise ExecutionError("session_not_owned")
            yield

    async def claim(self, epoch: int) -> None:
        async with self.lock:
            if self.owner != "waiting" or epoch != self.epoch:
                raise ExecutionError("stale_control_request")
            self.owner = "human"
            self.epoch += 1
            self.evidence.event("control_transferred", owner=self.owner, epoch=self.epoch)

    async def resume(self, epoch: int) -> None:
        async with self.lock:
            if self.owner != "human" or epoch != self.epoch:
                raise ExecutionError("stale_control_request")
            self.owner = "checking"
            self.epoch += 1
            self.evidence.event("resume_requested", owner=self.owner, epoch=self.epoch)
            self.resumed.set()

    async def abort(self, epoch: int) -> None:
        async with self.lock:
            if epoch != self.epoch or self.owner not in {"human", "waiting"}:
                raise ExecutionError("stale_control_request")
            self.cancelled = True
            self.resumed.set()

    async def handoff(
        self, reason: str, step: str, validate: Callable[[], Awaitable[None]]
    ) -> None:
        if not self.interactive:
            raise ExecutionError("intervention_required", expected=reason)
        self.interventions += 1
        async with self.lock:
            self.reason, self.step = reason, step
            self.owner = "waiting"
            self.epoch += 1
            self.resumed.clear()
            self.evidence.event("intervention_requested", code=reason, step=step, epoch=self.epoch)
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    await self.resumed.wait()
                    if self.cancelled:
                        raise ExecutionError("operator_aborted")
                    try:
                        await validate()
                    except ExecutionError as error:
                        async with self.lock:
                            self.owner = "waiting"
                            self.epoch += 1
                            self.reason = error.code
                            self.resumed.clear()
                            self.evidence.event(
                                "resume_rejected", code=error.code, epoch=self.epoch
                            )
                        continue
                    async with self.lock:
                        self.owner = "automation"
                        self.epoch += 1
                        self.reason = None
                        self.evidence.event(
                            "control_transferred", owner=self.owner, epoch=self.epoch
                        )
                    return
        except TimeoutError as error:
            raise ExecutionError("intervention_timeout") from error
        finally:
            if self.owner != "automation":
                self.owner = "closed"

    async def record_manual(self, payload: dict[str, object]) -> None:
        if self.owner != "human":
            return
        kind = payload.get("kind")
        tag = payload.get("tag")
        if kind in {"click", "input", "change", "submit"} and tag in {
            "BUTTON",
            "INPUT",
            "SELECT",
            "A",
            "CANVAS",
            "FORM",
            "OTHER",
        }:
            control = payload.get("control", "unclassified")
            if control not in {
                "Restore session",
                "Acknowledge notice",
                "Dismiss notice",
                "Member ID",
                "Nickname",
                "Product",
            }:
                control = "unclassified"
            self.evidence.event(
                "human_action",
                manual_kind=kind,
                target_tag=tag,
                manual_control=control,
                epoch=self.epoch,
            )
