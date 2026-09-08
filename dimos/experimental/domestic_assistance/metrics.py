# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Read-only metrics derived from complete, audited episode journals."""

import argparse
from itertools import pairwise
from pathlib import Path

from dimos.experimental.domestic_assistance.contracts import (
    Contract,
    DispatchStatus,
    Identifier,
    Origin,
    Outcome,
    Seconds,
)
from dimos.experimental.domestic_assistance.rollouts import (
    DecisionFinished,
    EpisodeFinished,
    EpisodeStarted,
    JournalEvent,
    audit_episode,
)


class OutcomeCounts(Contract):
    success: int = 0
    failed: int = 0
    timeout: int = 0
    unknown: int = 0
    cancelled: int = 0


class EpisodeMetrics(Contract):
    episode_id: Identifier
    task_id: Identifier
    scenario_id: Identifier
    split_group: Identifier
    method: str
    origin: Origin
    termination_reason: str
    mission_success: bool
    autonomous_success: bool
    experiment_valid: bool
    assistance_requested: bool
    intervention_count: int
    decisions: int
    executed_decisions: int
    rejected_preconditions: int
    repeated_decisions: int
    executor_outcomes: OutcomeCounts
    verification_outcomes: OutcomeCounts
    duration_s: Seconds


class AggregateMetrics(Contract):
    episodes: int
    auditable_valid_episodes: int
    mission_successes: int
    autonomous_successes: int
    mission_success_rate: float | None
    autonomous_success_rate: float | None
    total_decisions: int
    total_interventions: int
    mean_decisions: float | None
    mean_duration_s: float | None
    termination_counts: dict[str, int]


def _count_outcomes(outcomes: list[Outcome]) -> OutcomeCounts:
    return OutcomeCounts(
        success=outcomes.count(Outcome.SUCCESS),
        failed=outcomes.count(Outcome.FAILED),
        timeout=outcomes.count(Outcome.TIMEOUT),
        unknown=outcomes.count(Outcome.UNKNOWN),
        cancelled=outcomes.count(Outcome.CANCELLED),
    )


def derive_episode_metrics(path: Path) -> EpisodeMetrics:
    """Derive one metric row without modifying or supplementing its journal."""
    report = audit_episode(path)
    if not report.complete:
        raise ValueError(f"episode is not auditable: {report.errors}")
    events = [
        JournalEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    started = next(event.body for event in events if isinstance(event.body, EpisodeStarted))
    ended = next(event.body for event in events if isinstance(event.body, EpisodeFinished))
    entries = [
        event.body.history_entry for event in events if isinstance(event.body, DecisionFinished)
    ]
    executor_outcomes = [
        entry.executor_result.outcome for entry in entries if entry.executor_result is not None
    ]
    verification_outcomes = [entry.verification_result.outcome for entry in entries]
    repeated = sum(current.action == previous.action for previous, current in pairwise(entries))
    summary = ended.summary
    metadata = started.metadata
    return EpisodeMetrics(
        episode_id=metadata.episode_id,
        task_id=started.mission.task_id,
        scenario_id=metadata.scenario_id,
        split_group=metadata.split_group,
        method=metadata.manifest.method,
        origin=metadata.origin,
        termination_reason=summary.reason,
        mission_success=summary.mission_success,
        autonomous_success=summary.autonomous_success,
        experiment_valid=summary.experiment_valid,
        assistance_requested=summary.assistance_requested,
        intervention_count=summary.intervention_count,
        decisions=summary.decisions,
        executed_decisions=sum(
            entry.dispatch_status == DispatchStatus.EXECUTED for entry in entries
        ),
        rejected_preconditions=sum(
            entry.dispatch_status == DispatchStatus.REJECTED_PRECONDITION for entry in entries
        ),
        repeated_decisions=repeated,
        executor_outcomes=_count_outcomes(executor_outcomes),
        verification_outcomes=_count_outcomes(verification_outcomes),
        duration_s=summary.duration_s,
    )


def aggregate_metrics(paths: tuple[Path, ...]) -> AggregateMetrics:
    """Aggregate audited episodes; success rates exclude invalid experiments."""
    rows = tuple(derive_episode_metrics(path) for path in sorted(paths))
    eligible = tuple(row for row in rows if row.experiment_valid)
    count = len(eligible)
    mission_successes = sum(row.mission_success for row in eligible)
    autonomous_successes = sum(row.autonomous_success for row in eligible)
    termination_counts: dict[str, int] = {}
    for row in eligible:
        termination_counts[row.termination_reason] = (
            termination_counts.get(row.termination_reason, 0) + 1
        )
    return AggregateMetrics(
        episodes=len(rows),
        auditable_valid_episodes=count,
        mission_successes=mission_successes,
        autonomous_successes=autonomous_successes,
        mission_success_rate=mission_successes / count if count else None,
        autonomous_success_rate=autonomous_successes / count if count else None,
        total_decisions=sum(row.decisions for row in eligible),
        total_interventions=sum(row.intervention_count for row in eligible),
        mean_decisions=(sum(row.decisions for row in eligible) / count if count else None),
        mean_duration_s=(sum(row.duration_s for row in eligible) / count if count else None),
        termination_counts=termination_counts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journals", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    journal_paths = tuple(args.journals)
    result = aggregate_metrics(journal_paths).model_dump_json(indent=2)
    if args.output is None:
        print(result)
        return
    output = args.output.resolve()
    if output in {path.resolve() for path in journal_paths}:
        raise ValueError("metrics output cannot overwrite an input journal")
    output.write_text(result + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
