"""Small command surface; replay never imports or initializes an LLM client."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

import uvicorn

from capabilities.config import load_local_env
from capabilities.contracts import Capability, Failure, GoalContract, RunResult
from capabilities.engine import Executor, ReplayEngine
from capabilities.evidence import Evidence, atomic_write
from capabilities.operator import create_operator_app
from capabilities.policy import Policy
from capabilities.session import SessionController
from capabilities.surface import BrowserSurface

PACKAGE = Path(__file__).parent


def load_policy(origin: str) -> Policy:
    policy = Policy.model_validate_json((PACKAGE / "profiles/harbor.json").read_text())
    return policy.model_copy(update={"origin": origin.rstrip("/")})


async def run_browser(args: argparse.Namespace) -> RunResult:
    artifact = (
        Capability.model_validate_json(await asyncio.to_thread(Path(args.artifact).read_text))
        if args.command == "replay"
        else None
    )
    contract = (
        artifact.goal
        if artifact
        else GoalContract.model_validate_json(
            await asyncio.to_thread(Path(args.contract).read_text)
        )
    )
    supplied = json.loads(args.inputs)
    inputs = contract.validate_inputs(supplied)
    key = ""
    if args.command == "discover":
        key_name = "GEMINI_API_KEY" if args.provider == "gemini" else "ANTHROPIC_API_KEY"
        key = os.environ.get(key_name, "")
        if not key:
            raise ValueError(f"{key_name} is required for genuine discovery; replay needs no key")
    secrets = [inputs[name] for name, spec in contract.inputs.items() if spec.sensitive]
    if key:
        secrets.append(key)
    run_id = f"{args.command}-{uuid.uuid4().hex[:12]}"
    evidence = Evidence(Path(args.evidence), run_id, secrets)
    policy = load_policy(args.origin)
    control = SessionController(evidence, policy.intervention_seconds, interactive=args.headed)
    surface = BrowserSurface(
        policy,
        evidence,
        control,
        headless=not args.headed,
        channel=os.environ.get("CAPABILITIES_BROWSER_CHANNEL"),
    )
    server: uvicorn.Server | None = None
    server_task: asyncio.Task[None] | None = None
    planner: Any = None
    try:
        if args.headed:
            origin = f"http://127.0.0.1:{args.operator_port}"
            server = uvicorn.Server(
                uvicorn.Config(
                    create_operator_app(control, origin),
                    host="127.0.0.1",
                    port=args.operator_port,
                    access_log=False,
                    log_level="warning",
                )
            )
            server_task = asyncio.create_task(server.serve())
            while not server.started:
                if server_task.done():
                    await server_task
                    raise ValueError("Operator server could not start")
                await asyncio.sleep(0.03)
            print(f"Operator console: {origin} (same live Chromium session)", file=sys.stderr)
        url = f"{args.origin.rstrip('/')}/?scenario={args.scenario}"
        await surface.start(url)
        executor = Executor(surface, policy, control, evidence)
        if artifact:
            result = await ReplayEngine(executor).run(artifact, supplied)
        else:
            from capabilities.discovery import AnthropicPlanner, DiscoveryEngine

            if args.provider == "gemini":
                from capabilities.gemini import GeminiPlanner

                model = args.model or os.environ.get(
                    "CAPABILITIES_GEMINI_MODEL", "gemini-3.1-flash-lite"
                )
                planner = GeminiPlanner(key, model, evidence)
            else:
                model = args.model or os.environ.get("CAPABILITIES_MODEL", "claude-sonnet-5-5")
                planner = AnthropicPlanner(key, model, evidence)
            result = await DiscoveryEngine(executor, planner).run(args.goal, contract, supplied)
        if result.status == "success":
            await surface.capture()
    except Exception:
        result = RunResult(
            status="failure", run_id=run_id, error=Failure(code="startup_or_runtime_error")
        )
        evidence.result(result)
    finally:
        control.owner = "closed"
        if planner:
            await planner.close()
        await surface.close()
        if server:
            server.should_exit = True
        if server_task:
            with suppress(asyncio.CancelledError):
                await server_task
    print(f"Evidence: {evidence.root}", file=sys.stderr)
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("sandbox", help="Serve the synthetic legacy banking UI")
    serve.add_argument("--port", type=int, default=8765)
    web = commands.add_parser("web", help="Start the web dashboard and its banking sandbox")
    web.add_argument("--port", type=int, default=8766)
    web.add_argument("--bank-port", type=int, default=8767)
    web.add_argument("--evidence", default="runs/web")
    schema = commands.add_parser("schema", help="Export the artifact JSON Schema")
    schema.add_argument("--out", default="schemas/capability.schema.json")
    for command in ("discover", "replay"):
        child = commands.add_parser(command)
        child.add_argument("--origin", default="http://127.0.0.1:8765")
        child.add_argument(
            "--inputs", required=True, help="JSON object matching the capability input contract"
        )
        child.add_argument("--headed", action="store_true", help="Enable real human takeover")
        child.add_argument("--operator-port", type=int, default=8766)
        child.add_argument("--scenario", default="normal")
        child.add_argument("--evidence", default="runs")
        child.add_argument(
            "--show-outputs", action="store_true", help="Print raw declared outputs to this caller"
        )
        if command == "discover":
            child.add_argument("--goal", required=True)
            child.add_argument("--contract", default="examples/prepare-subaccount.goal.json")
            child.add_argument(
                "--provider",
                choices=("anthropic", "gemini"),
                default=os.environ.get("CAPABILITIES_PROVIDER", "anthropic"),
            )
            child.add_argument("--model", help="Override the selected provider's default model")
        else:
            child.add_argument("--artifact", required=True)
    return root


def main() -> None:
    load_local_env()
    args = parser().parse_args()
    if args.command == "web":
        from capabilities.dashboard import serve_dashboard

        try:
            asyncio.run(serve_dashboard(args.port, args.bank_port, Path(args.evidence)))
        except OSError:
            print(
                "A local port is unavailable. Stop the previous dashboard or choose --port and --bank-port.",
                file=sys.stderr,
            )
            raise SystemExit(2) from None
        except KeyboardInterrupt:
            pass
        return
    if args.command == "sandbox":
        uvicorn.run(
            "capabilities.sandbox.app:app", host="127.0.0.1", port=args.port, access_log=False
        )
        return
    if args.command == "schema":
        atomic_write(Path(args.out), json.dumps(Capability.model_json_schema(), indent=2))
        return
    try:
        result = asyncio.run(run_browser(args))
    except (ValueError, OSError):
        print(
            "Invalid configuration or input. Check paths, the input contract, and API configuration.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    payload = result.model_dump(mode="json")
    if not args.show_outputs:
        payload["outputs"] = {name: "[REDACTED]" for name in result.outputs}
    print(json.dumps(payload, indent=2))
    raise SystemExit(1 if result.status == "failure" else 0)


if __name__ == "__main__":
    main()
