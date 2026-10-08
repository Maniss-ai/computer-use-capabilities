"""Check required deliverables; fixture discovery can NEVER satisfy the live-run gate."""

import argparse
import json
from pathlib import Path

from capabilities.contracts import Capability
from capabilities.evidence import capability_digest

HEADINGS = [
    "Architecture",
    "Artifact schema",
    "Determinism & error handling",
    "Heterogeneity & multi-tenant",
    "Escalation & handoff",
    "Safety",
    "Cuts",
]


def check(offline: bool) -> list[str]:
    failures = []
    for file in [
        "README.md",
        "REPORT.md",
        "uv.lock",
        "schemas/capability.schema.json",
        "evidence/README.md",
    ]:
        if not Path(file).is_file():
            failures.append(f"Missing {file}")
    report = Path("REPORT.md").read_text() if Path("REPORT.md").exists() else ""
    for heading in HEADINGS:
        if f"## {heading}" not in report:
            failures.append(f"Missing report heading: {heading}")
    artifacts = list(Path("evidence").rglob("capability.json"))
    live = []
    for path in artifacts:
        artifact = Capability.model_validate_json(path.read_text())
        if artifact.provenance.source != "llm_discovery":
            continue
        events_path = path.parent / "events.jsonl"
        if not events_path.exists():
            continue
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        if any(e["event"] == "model_response" and e.get("response_id") for e in events) and any(
            e["event"] == "success_verified" for e in events
        ):
            digest = capability_digest(artifact)
            if any(
                e["event"] == "artifact_saved" and e.get("artifact_sha256") == digest
                for e in events
            ) and any(
                e["event"] == "run_finished"
                and e.get("status") == "success"
                and e.get("model_calls", 0) > 0
                for e in events
            ):
                live.append(digest)
    if not live and not offline:
        failures.append(
            "No genuine successful LLM discovery evidence. Run discover with configured API access."
        )
    if live and not offline:
        verified_replay = False
        for path in Path("evidence").rglob("events.jsonl"):
            events = [json.loads(line) for line in path.read_text().splitlines()]
            same_artifact = any(
                e["event"] == "replay_started" and e.get("artifact_sha256") in live for e in events
            )
            completed = any(
                e["event"] == "run_finished"
                and e.get("status") == "success"
                and e.get("model_calls") == 0
                for e in events
            )
            verified_replay = verified_replay or (same_artifact and completed)
        if not verified_replay:
            failures.append(
                "No successful model-free replay matching the live-discovered artifact hash."
            )
    if not artifacts:
        failures.append("No saved capability in evidence/")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Check offline deliverables; do not claim submission readiness",
    )
    args = parser.parse_args()
    failures = check(args.offline)
    for failure in failures:
        print(f"INCOMPLETE: {failure}")
    if not failures:
        print(
            "Offline deliverables verified; live discovery remains a separate gate."
            if args.offline
            else "Required evidence checks passed. Review evidence and public repository before submission."
        )
    raise SystemExit(bool(failures))
