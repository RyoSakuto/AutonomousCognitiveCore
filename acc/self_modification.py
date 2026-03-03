from __future__ import annotations

from dataclasses import dataclass

from .config import ACCConfig
from .state import StateSnapshot, StateStore


@dataclass
class RuntimePolicy:
    uncertainty_threshold: float
    conflict_threshold: float
    novelty_threshold: float
    exploration_factor: float
    memory_retrieval_k: int
    memory_min_score: float

    @classmethod
    def from_config(cls, config: ACCConfig) -> "RuntimePolicy":
        return cls(
            uncertainty_threshold=config.uncertainty_threshold,
            conflict_threshold=config.conflict_threshold,
            novelty_threshold=config.novelty_threshold,
            exploration_factor=config.exploration_factor,
            memory_retrieval_k=config.memory_retrieval_k,
            memory_min_score=config.memory_min_score,
        )

    def to_map(self) -> dict[str, float]:
        return {
            "uncertainty_threshold": self.uncertainty_threshold,
            "conflict_threshold": self.conflict_threshold,
            "novelty_threshold": self.novelty_threshold,
            "exploration_factor": self.exploration_factor,
            "memory_retrieval_k": float(self.memory_retrieval_k),
            "memory_min_score": self.memory_min_score,
        }

    def with_updates(self, values: dict[str, float]) -> "RuntimePolicy":
        return RuntimePolicy(
            uncertainty_threshold=float(values.get("uncertainty_threshold", self.uncertainty_threshold)),
            conflict_threshold=float(values.get("conflict_threshold", self.conflict_threshold)),
            novelty_threshold=float(values.get("novelty_threshold", self.novelty_threshold)),
            exploration_factor=float(values.get("exploration_factor", self.exploration_factor)),
            memory_retrieval_k=max(1, int(values.get("memory_retrieval_k", self.memory_retrieval_k))),
            memory_min_score=float(values.get("memory_min_score", self.memory_min_score)),
        )


@dataclass
class ChangeProposal:
    parameter: str
    old_value: float
    new_value: float
    rationale: str
    expected_effect: str
    risk_level: float
    priority_score: float = 0.0
    coupled: bool = False


class SelfModificationManager:
    PARAM_LIMITS = {
        "uncertainty_threshold": (0.45, 0.85, 0.06),
        "conflict_threshold": (0.40, 0.80, 0.06),
        "novelty_threshold": (0.45, 0.85, 0.06),
        "exploration_factor": (0.10, 0.65, 0.08),
        "memory_retrieval_k": (2.0, 8.0, 1.0),
        "memory_min_score": (0.08, 0.40, 0.08),
    }
    MODE_ALLOWED_PARAMS = {
        "discovery": {
            "uncertainty_threshold",
            "conflict_threshold",
            "novelty_threshold",
            "exploration_factor",
            "memory_retrieval_k",
            "memory_min_score",
        },
        "balanced": {
            "uncertainty_threshold",
            "conflict_threshold",
            "novelty_threshold",
            "exploration_factor",
            "memory_retrieval_k",
            "memory_min_score",
        },
        "guarded": {
            "uncertainty_threshold",
            "conflict_threshold",
            "memory_retrieval_k",
            "memory_min_score",
        },
        "production": {
            "uncertainty_threshold",
            "conflict_threshold",
            "memory_retrieval_k",
        },
    }

    def __init__(self, state: StateStore, config: ACCConfig) -> None:
        self.state = state
        self.config = config
        self.policy = RuntimePolicy.from_config(config)
        self._pending_rollback: dict[int, dict[str, float | int]] = {}
        self._last_rollback_alert_cycle: int = -1

    def bootstrap(self) -> RuntimePolicy:
        self.state.bootstrap_runtime_params(self.policy.to_map())
        values = self.state.get_runtime_params()
        self.policy = self.policy.with_updates(values)
        return self.policy

    def _current_mode(self) -> str:
        mode = str(self.config.operating_mode or "").strip().lower()
        if mode in self.MODE_ALLOWED_PARAMS:
            return mode
        return "balanced"

    @staticmethod
    def _parse_csv_set(raw: str) -> set[str]:
        out: set[str] = set()
        for item in str(raw or "").split(","):
            token = item.strip().lower()
            if token:
                out.add(token)
        return out

    def _allowed_parameters(self) -> set[str]:
        mode = self._current_mode()
        allowed = set(self.MODE_ALLOWED_PARAMS.get(mode, self.MODE_ALLOWED_PARAMS["balanced"]))
        explicit_allow = self._parse_csv_set(self.config.self_mod_allow_params)
        explicit_deny = self._parse_csv_set(self.config.self_mod_deny_params)

        if explicit_allow:
            allowed = allowed.intersection(explicit_allow)
        if explicit_deny:
            allowed = {param for param in allowed if param not in explicit_deny}
        return allowed

    def _validate_proposal(self, proposal: ChangeProposal) -> tuple[bool, str]:
        limits = self.PARAM_LIMITS.get(proposal.parameter)
        if not limits:
            return False, "parameter_not_allowed"

        allowed = self._allowed_parameters()
        if proposal.parameter not in allowed:
            return False, f"mode_policy_denied:{self._current_mode()}"

        low, high, max_delta = limits
        if proposal.new_value < low or proposal.new_value > high:
            return False, "outside_allowed_range"
        if abs(proposal.new_value - proposal.old_value) > max_delta:
            return False, "delta_too_large"

        return True, "ok"

    def _simulation_score(self, proposal: ChangeProposal, snapshot: StateSnapshot) -> float:
        score = 0.0

        if proposal.parameter == "uncertainty_threshold" and proposal.new_value < proposal.old_value:
            score += 0.2 if snapshot.tension < 0.25 else 0.1
        if proposal.parameter == "memory_retrieval_k" and proposal.new_value > proposal.old_value:
            score += 0.12 if snapshot.uncertainty > 0.25 else 0.06
        if proposal.parameter == "exploration_factor" and proposal.new_value > proposal.old_value:
            score += 0.08 if snapshot.novelty > 0.55 else 0.03
        if proposal.parameter == "memory_min_score" and proposal.new_value < proposal.old_value:
            score += 0.07

        if proposal.coupled:
            score -= 0.02
        score -= proposal.risk_level * 0.25
        return round(score, 4)

    def _estimate_risk(self, parameter: str, old_value: float, new_value: float) -> float:
        limits = self.PARAM_LIMITS.get(parameter)
        if not limits:
            return 1.0
        max_delta = float(limits[2])
        if max_delta <= 0:
            return 1.0
        return min(1.0, abs(new_value - old_value) / max_delta)

    def _bounded_value(self, parameter: str, value: float) -> float:
        limits = self.PARAM_LIMITS.get(parameter)
        if not limits:
            return value
        low, high, _ = limits
        return max(low, min(high, value))

    def _candidate_score(
        self,
        proposal: ChangeProposal,
        snapshot: StateSnapshot,
        history_stats: dict[str, dict],
        u_trend: float,
    ) -> float:
        stat = history_stats.get(proposal.parameter, {})
        approved = int(stat.get("approved_count", 0))
        rejected = int(stat.get("rejected_count", 0))
        rolled_back = int(stat.get("rolled_back_count", 0))
        avg_sim = float(stat.get("avg_simulation_score", 0.0))

        score = 0.22 + self._simulation_score(proposal, snapshot)
        score += approved * 0.025
        score -= rejected * 0.018
        score -= rolled_back * 0.035
        score += max(0.0, avg_sim) * 0.12

        if proposal.parameter == "exploration_factor" and u_trend > 0.0:
            score += 0.04
        if proposal.parameter == "memory_retrieval_k" and u_trend > 0.05:
            score += 0.03
        if proposal.parameter == "uncertainty_threshold" and u_trend < -0.04:
            score -= 0.03
        return round(score, 4)

    def _build_coupled_proposals(
        self,
        primary: ChangeProposal,
    ) -> list[ChangeProposal]:
        coupled: list[ChangeProposal] = []

        if primary.parameter == "memory_retrieval_k" and primary.new_value > primary.old_value:
            old_min = self.policy.memory_min_score
            new_min = self._bounded_value("memory_min_score", old_min - 0.02)
            if abs(new_min - old_min) > 1e-8:
                coupled.append(
                    ChangeProposal(
                        parameter="memory_min_score",
                        old_value=old_min,
                        new_value=new_min,
                        rationale=f"coupled_with_{primary.parameter}",
                        expected_effect="keep_retrieval_recall_balanced",
                        risk_level=self._estimate_risk("memory_min_score", old_min, new_min),
                        coupled=True,
                    )
                )

        if primary.parameter == "exploration_factor":
            if primary.new_value < primary.old_value:
                old_n = self.policy.novelty_threshold
                new_n = self._bounded_value("novelty_threshold", old_n - 0.02)
                if abs(new_n - old_n) > 1e-8:
                    coupled.append(
                        ChangeProposal(
                            parameter="novelty_threshold",
                            old_value=old_n,
                            new_value=new_n,
                            rationale=f"coupled_with_{primary.parameter}",
                            expected_effect="maintain_creativity_trigger_when_exploration_drops",
                            risk_level=self._estimate_risk("novelty_threshold", old_n, new_n),
                            coupled=True,
                        )
                    )
            elif primary.new_value > primary.old_value:
                old_u = self.policy.uncertainty_threshold
                new_u = self._bounded_value("uncertainty_threshold", old_u + 0.02)
                if abs(new_u - old_u) > 1e-8:
                    coupled.append(
                        ChangeProposal(
                            parameter="uncertainty_threshold",
                            old_value=old_u,
                            new_value=new_u,
                            rationale=f"coupled_with_{primary.parameter}",
                            expected_effect="avoid_goal_overproduction_during_high_exploration",
                            risk_level=self._estimate_risk("uncertainty_threshold", old_u, new_u),
                            coupled=True,
                        )
                    )

        if primary.parameter == "uncertainty_threshold" and primary.new_value < primary.old_value:
            old_c = self.policy.conflict_threshold
            new_c = self._bounded_value("conflict_threshold", old_c - 0.01)
            if abs(new_c - old_c) > 1e-8:
                coupled.append(
                    ChangeProposal(
                        parameter="conflict_threshold",
                        old_value=old_c,
                        new_value=new_c,
                        rationale=f"coupled_with_{primary.parameter}",
                        expected_effect="align_conflict_trigger_with_more_aggressive_goaling",
                        risk_level=self._estimate_risk("conflict_threshold", old_c, new_c),
                        coupled=True,
                    )
                )

        return coupled

    def _propose(self, cycle: int, snapshot: StateSnapshot) -> list[ChangeProposal]:
        if not self.config.self_mod_enabled:
            return []

        last_approved = self.state.get_latest_approved_self_mod_cycle()
        if last_approved is not None:
            if cycle - last_approved < self.config.self_mod_min_cycles_between_changes:
                return []

        recent_metrics = self.state.get_recent_metrics(5)
        recent_idle = self.state.count_recent_idle_cycles(8)
        decision_counts = self.state.get_recent_decision_counts(12)
        history_stats = self.state.get_self_mod_parameter_stats(window=80)

        commit_count = decision_counts.get("commit", 0)
        branch_count = decision_counts.get("branch", 0)
        u_trend = 0.0
        if len(recent_metrics) >= 4:
            u_trend = float(recent_metrics[-1]["uncertainty"]) - float(recent_metrics[0]["uncertainty"])

        candidates: list[ChangeProposal] = []

        if recent_idle >= 4 and snapshot.open_goals == 0 and snapshot.tension < 0.22:
            old = self.policy.uncertainty_threshold
            new = self._bounded_value("uncertainty_threshold", old - 0.03)
            candidates.append(
                ChangeProposal(
                    parameter="uncertainty_threshold",
                    old_value=old,
                    new_value=new,
                    rationale="idle_streak_detected",
                    expected_effect="increase_intrinsic_goal_frequency",
                    risk_level=self._estimate_risk("uncertainty_threshold", old, new),
                )
            )

        if snapshot.open_goals >= 2 and snapshot.uncertainty > 0.35:
            old_k = float(self.policy.memory_retrieval_k)
            new_k = self._bounded_value("memory_retrieval_k", old_k + 1.0)
            if new_k > old_k:
                candidates.append(
                    ChangeProposal(
                        parameter="memory_retrieval_k",
                        old_value=old_k,
                        new_value=new_k,
                        rationale="high_load_context_need",
                        expected_effect="improve_context_reuse_and_commit_quality",
                        risk_level=self._estimate_risk("memory_retrieval_k", old_k, new_k),
                    )
                )

        if u_trend > 0.10 and snapshot.uncertainty > 0.45:
            old = self.policy.exploration_factor
            new = self._bounded_value("exploration_factor", old - 0.04)
            candidates.append(
                ChangeProposal(
                    parameter="exploration_factor",
                    old_value=old,
                    new_value=new,
                    rationale="uncertainty_trend_rising",
                    expected_effect="stabilize_decision_path_and_reduce_noise",
                    risk_level=self._estimate_risk("exploration_factor", old, new),
                )
            )

        if commit_count >= 6 and branch_count == 0 and snapshot.novelty > 0.50:
            old = self.policy.exploration_factor
            new = self._bounded_value("exploration_factor", old + 0.03)
            candidates.append(
                ChangeProposal(
                    parameter="exploration_factor",
                    old_value=old,
                    new_value=new,
                    rationale="exploration_debt_detected",
                    expected_effect="reintroduce_counterfactual_search",
                    risk_level=self._estimate_risk("exploration_factor", old, new),
                )
            )

        if not candidates:
            return []

        for proposal in candidates:
            proposal.priority_score = self._candidate_score(
                proposal=proposal,
                snapshot=snapshot,
                history_stats=history_stats,
                u_trend=u_trend,
            )
        primary = max(candidates, key=lambda p: p.priority_score)
        if primary.priority_score <= 0.02:
            return []

        proposals = [primary]
        coupled = self._build_coupled_proposals(primary)
        for item in coupled:
            item.priority_score = round(primary.priority_score - 0.03, 4)
        proposals.extend(coupled)
        return proposals

    def _apply_policy_update(self, parameter: str, value: float) -> None:
        self.state.upsert_runtime_param(parameter, value)
        self.policy = self.policy.with_updates({parameter: value})

    def _register_rollback_watch(
        self,
        proposal_id: int,
        cycle: int,
        proposal: ChangeProposal,
        baseline_uncertainty: float,
    ) -> None:
        self._pending_rollback[proposal_id] = {
            "cycle": float(cycle),
            "parameter": proposal.parameter,
            "old_value": proposal.old_value,
            "new_value": proposal.new_value,
            "baseline_uncertainty": baseline_uncertainty,
        }

    def _handle_rollbacks(self, cycle: int) -> None:
        if not self._pending_rollback:
            return

        metrics = self.state.get_recent_metrics(self.config.self_mod_rollback_window)
        if len(metrics) < self.config.self_mod_rollback_window:
            return

        avg_uncertainty = sum(float(m["uncertainty"]) for m in metrics) / len(metrics)

        done: list[int] = []
        for proposal_id, entry in self._pending_rollback.items():
            applied_cycle = int(entry["cycle"])
            if cycle - applied_cycle < self.config.self_mod_rollback_window:
                continue

            baseline = float(entry["baseline_uncertainty"])
            parameter = str(entry["parameter"])
            old_value = float(entry["old_value"])
            new_value = float(entry["new_value"])

            if avg_uncertainty > baseline + self.config.self_mod_regression_margin:
                self._apply_policy_update(parameter, old_value)
                self.state.update_self_mod_proposal_status(
                    proposal_id,
                    status="rolled_back",
                    note=f"uncertainty_regression avg={avg_uncertainty:.3f} baseline={baseline:.3f}",
                )
                self.state.add_self_mod_audit(
                    cycle=cycle,
                    proposal_id=proposal_id,
                    action="rollback",
                    detail=(
                        f"parameter={parameter} reverted_to={old_value:.4f} "
                        f"previous={new_value:.4f} avg_uncertainty={avg_uncertainty:.3f}"
                    ),
                )
            else:
                self.state.add_self_mod_audit(
                    cycle=cycle,
                    proposal_id=proposal_id,
                    action="post_check",
                    detail=(
                        f"kept_change parameter={parameter} value={new_value:.4f} "
                        f"avg_uncertainty={avg_uncertainty:.3f}"
                    ),
                )
            done.append(proposal_id)

        for proposal_id in done:
            self._pending_rollback.pop(proposal_id, None)

    def _budget_available(self, cycle: int) -> tuple[bool, dict[str, int]]:
        window = max(1, int(self.config.self_mod_budget_window_cycles))
        max_approved = max(0, int(self.config.self_mod_max_approved_per_window))
        start_cycle = max(1, int(cycle) - window + 1)
        approved_count = self.state.count_self_mod_proposals(
            status="approved",
            cycle_from=start_cycle,
            cycle_to=int(cycle),
        )
        return approved_count < max_approved, {
            "window": window,
            "max_approved": max_approved,
            "approved_count": approved_count,
            "start_cycle": start_cycle,
        }

    def _emit_rollback_alert_if_needed(self, cycle: int) -> None:
        window = max(1, int(self.config.self_mod_rollback_alert_window))
        threshold = max(1, int(self.config.self_mod_rollback_alert_threshold))
        counts = self.state.get_self_mod_status_counts_in_cycle_window(cycle=cycle, window=window)
        rolled_back = int(counts.get("rolled_back", 0))
        if rolled_back < threshold:
            return

        min_gap = max(1, window // 2)
        if self._last_rollback_alert_cycle >= 0 and cycle - self._last_rollback_alert_cycle < min_gap:
            return

        self.state.add_agent_event(
            cycle=cycle,
            event_type="self_mod_rollback_alert",
            severity="warning",
            message=(
                f"High rollback frequency detected: rolled_back={rolled_back} "
                f"in last {window} cycles"
            ),
            payload={
                "rolled_back": rolled_back,
                "threshold": threshold,
                "window_cycles": window,
                "mode": self._current_mode(),
            },
        )
        self.state.add_episode(
            cycle=cycle,
            kind="self_mod_alert",
            content=(
                f"rollback_alert rolled_back={rolled_back} "
                f"threshold={threshold} window={window}"
            ),
            score=min(1.0, float(rolled_back) / float(threshold)),
        )
        self._last_rollback_alert_cycle = int(cycle)

    def _evaluate_and_apply_proposal(
        self,
        cycle: int,
        snapshot: StateSnapshot,
        proposal: ChangeProposal,
        baseline_uncertainty: float,
        optional: bool = False,
    ) -> bool:
        valid, reason = self._validate_proposal(proposal)
        simulation_score = self._simulation_score(proposal, snapshot)
        note_suffix = (
            f"priority={proposal.priority_score:.4f};coupled={proposal.coupled};optional={optional}"
        )

        if not valid:
            proposal_id = self.state.create_self_mod_proposal(
                cycle=cycle,
                parameter=proposal.parameter,
                old_value=proposal.old_value,
                new_value=proposal.new_value,
                rationale=proposal.rationale,
                expected_effect=proposal.expected_effect,
                risk_level=proposal.risk_level,
                simulation_score=simulation_score,
                status="rejected",
                note=f"{reason};{note_suffix}",
            )
            self.state.add_self_mod_audit(
                cycle=cycle,
                proposal_id=proposal_id,
                action="gate_reject",
                detail=f"reason={reason} simulation_score={simulation_score:.4f} {note_suffix}",
            )
            return False

        if simulation_score <= 0.0:
            proposal_id = self.state.create_self_mod_proposal(
                cycle=cycle,
                parameter=proposal.parameter,
                old_value=proposal.old_value,
                new_value=proposal.new_value,
                rationale=proposal.rationale,
                expected_effect=proposal.expected_effect,
                risk_level=proposal.risk_level,
                simulation_score=simulation_score,
                status="rejected",
                note=f"simulation_non_positive;{note_suffix}",
            )
            self.state.add_self_mod_audit(
                cycle=cycle,
                proposal_id=proposal_id,
                action="simulation_reject",
                detail=f"simulation_score={simulation_score:.4f} {note_suffix}",
            )
            return False

        proposal_id = self.state.create_self_mod_proposal(
            cycle=cycle,
            parameter=proposal.parameter,
            old_value=proposal.old_value,
            new_value=proposal.new_value,
            rationale=proposal.rationale,
            expected_effect=proposal.expected_effect,
            risk_level=proposal.risk_level,
            simulation_score=simulation_score,
            status="approved",
            note=f"gate_and_simulation_passed;{note_suffix}",
        )

        self._apply_policy_update(proposal.parameter, proposal.new_value)
        self._register_rollback_watch(
            proposal_id=proposal_id,
            cycle=cycle,
            proposal=proposal,
            baseline_uncertainty=baseline_uncertainty,
        )
        self.state.add_self_mod_audit(
            cycle=cycle,
            proposal_id=proposal_id,
            action="applied",
            detail=(
                f"parameter={proposal.parameter} old={proposal.old_value:.4f} "
                f"new={proposal.new_value:.4f} simulation_score={simulation_score:.4f} {note_suffix}"
            ),
        )
        return True

    def process_cycle(self, cycle: int, snapshot: StateSnapshot) -> RuntimePolicy:
        self._handle_rollbacks(cycle)
        self._emit_rollback_alert_if_needed(cycle)
        proposals = self._propose(cycle, snapshot)
        if not proposals:
            return self.policy

        budget_ok, budget_meta = self._budget_available(cycle)
        if not budget_ok:
            primary = proposals[0]
            simulation_score = self._simulation_score(primary, snapshot)
            proposal_id = self.state.create_self_mod_proposal(
                cycle=cycle,
                parameter=primary.parameter,
                old_value=primary.old_value,
                new_value=primary.new_value,
                rationale=primary.rationale,
                expected_effect=primary.expected_effect,
                risk_level=primary.risk_level,
                simulation_score=simulation_score,
                status="rejected",
                note=(
                    "budget_exceeded;"
                    f"window={budget_meta['window']};"
                    f"approved_count={budget_meta['approved_count']};"
                    f"max_approved={budget_meta['max_approved']}"
                ),
            )
            self.state.add_self_mod_audit(
                cycle=cycle,
                proposal_id=proposal_id,
                action="budget_reject",
                detail=(
                    f"parameter={primary.parameter} approved_count={budget_meta['approved_count']} "
                    f"max_approved={budget_meta['max_approved']} window={budget_meta['window']}"
                ),
            )
            self.state.add_agent_event(
                cycle=cycle,
                event_type="self_mod_budget_block",
                severity="warning",
                message=(
                    f"Self-mod budget blocked proposal for {primary.parameter} "
                    f"(approved={budget_meta['approved_count']}/{budget_meta['max_approved']})"
                ),
                payload={"parameter": primary.parameter, **budget_meta, "mode": self._current_mode()},
            )
            return self.policy

        baseline_metrics = self.state.get_recent_metrics(3)
        baseline_uncertainty = (
            sum(float(m["uncertainty"]) for m in baseline_metrics) / len(baseline_metrics)
            if baseline_metrics
            else snapshot.uncertainty
        )

        primary = proposals[0]
        if not self._evaluate_and_apply_proposal(
            cycle=cycle,
            snapshot=snapshot,
            proposal=primary,
            baseline_uncertainty=baseline_uncertainty,
            optional=False,
        ):
            return self.policy

        for coupled in proposals[1:]:
            self._evaluate_and_apply_proposal(
                cycle=cycle,
                snapshot=snapshot,
                proposal=coupled,
                baseline_uncertainty=baseline_uncertainty,
                optional=True,
            )

        return self.policy
