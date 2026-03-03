#!/usr/bin/env python3
"""Run deterministic route regressions and emit a JSON score report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from game.route_regression_specs import ROUTE_REGRESSION_SPECS, RouteRegressionSpec, iter_route_regression_specs  # noqa: E402
from game.vertical_slice import CAMPAIGN_LEVELS, GameState, build_game_config, process_input  # noqa: E402

ROUTE_OUTCOMES: tuple[str, ...] = ("win", "lose")


def build_level_config(layout_name: str):
    level = next((item for item in CAMPAIGN_LEVELS if item.layout_name == layout_name), None)
    if level is None:
        return build_game_config(layout_name=layout_name, hazard_density="normal"), None
    return (
        build_game_config(
            layout_name=level.layout_name,
            hazard_density=level.hazard_density,
            hazard_count=level.hazard_count,
            starting_hp=level.starting_hp,
            turn_limit=level.turn_limit,
            enemy_turns_per_round=level.enemy_turns_per_round,
            enemy_route_cutoff_weight=level.enemy_route_cutoff_weight,
            enemy_chase_weight=level.enemy_chase_weight,
            score_balance=level.score_balance,
        ),
        level.level_id,
    )


def run_single_route(layout_name: str, spec: RouteRegressionSpec) -> dict[str, object]:
    config, level_id = build_level_config(layout_name)
    state = GameState(config=config)
    commands = tuple(spec.commands)

    consumed_commands = 0
    ended_before_commands_finished = False
    for command in commands:
        if state.status != "running":
            ended_before_commands_finished = True
            break
        consumed_commands += 1
        process_input(state, command)

    status_matches = state.status == spec.expected_status
    score_min, score_max = spec.score_range
    score_in_range = score_min <= state.run_score <= score_max
    passed = status_matches and score_in_range and not ended_before_commands_finished

    return {
        "layout_name": layout_name,
        "level_id": level_id or "unknown",
        "profile_id": spec.profile_id,
        "route_name": spec.expected_status,
        "commands": spec.commands,
        "hazard_density": config.hazard_density,
        "hazard_count": len(config.hazard_tiles),
        "starting_hp": config.starting_hp,
        "turn_limit": config.turn_limit,
        "enemy_turns_per_round": config.enemy_turns_per_round,
        "commands_total": len(commands),
        "commands_consumed": consumed_commands,
        "ended_before_commands_finished": ended_before_commands_finished,
        "expected_status": spec.expected_status,
        "actual_status": state.status,
        "status_matches": status_matches,
        "score": state.run_score,
        "expected_score_range": {
            "min": score_min,
            "max": score_max,
        },
        "score_in_expected_range": score_in_range,
        "hp": state.hp,
        "turns_left": state.turns_left,
        "player_pos": state.player_pos,
        "enemy_pos": state.enemy_pos,
        "passed": passed,
    }


def summarize_by_layout(route_results: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for layout_name in sorted(ROUTE_REGRESSION_SPECS):
        layout_results = [result for result in route_results if result["layout_name"] == layout_name]
        summary_entry: dict[str, object] = {
            "level_id": next((level.level_id for level in CAMPAIGN_LEVELS if level.layout_name == layout_name), "unknown"),
        }
        for route_name in ROUTE_OUTCOMES:
            scores = [
                int(result["score"])
                for result in layout_results
                if result["expected_status"] == route_name
            ]
            summary_entry[route_name] = {
                "route_count": len(scores),
                "min_score": min(scores) if scores else None,
                "max_score": max(scores) if scores else None,
            }
        summary[layout_name] = summary_entry
    return summary


def build_report() -> dict[str, object]:
    route_results: list[dict[str, object]] = []
    for layout_name in sorted(ROUTE_REGRESSION_SPECS):
        for spec in iter_route_regression_specs(layout_name):
            route_results.append(run_single_route(layout_name, spec))

    all_routes_passed = all(bool(result["passed"]) for result in route_results)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "all_routes_passed": all_routes_passed,
        "route_count": len(route_results),
        "routes": route_results,
        "summary_by_layout": summarize_by_layout(route_results),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic regression routes and report score balance as JSON."
    )
    parser.add_argument(
        "--output",
        default="route_balance_report.json",
        help="JSON report output path.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the JSON report to stdout.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if route assertions fail.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report()
    json_payload = json.dumps(report, ensure_ascii=True, indent=2)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{json_payload}\n", encoding="utf-8")

    if args.stdout:
        print(json_payload)
    else:
        print(f"Route-Balance-Report geschrieben: {output_path}")
        print(f"Alle Routen bestanden: {report['all_routes_passed']}")

    if args.strict and not report["all_routes_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
