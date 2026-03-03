#!/usr/bin/env python3
"""Analyze choose_enemy_step sensitivity across route_cutoff/chase weight ratios."""

from __future__ import annotations

import argparse
import json
import math
import sys
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from game.route_regression_specs import get_route_regression_spec_for_outcome  # noqa: E402
from game.vertical_slice import (  # noqa: E402
    CAMPAIGN_LEVELS,
    GameState,
    build_enemy_step_score,
    build_enemy_control_keys,
    build_extraction_route_zone,
    build_game_config,
    choose_enemy_step,
    distance_to_zone,
    enemy_step_score_fields,
    list_enemy_step_candidates,
    manhattan_distance,
    process_input,
)


@dataclass(frozen=True)
class WeightCombo:
    route_cutoff: int
    chase: int

    @property
    def label(self) -> str:
        return f"{self.route_cutoff}:{self.chase}"


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    level_id: str
    layout_name: str
    route_name: str
    route_step_index: int
    route_commands_total: int
    source_command: str | None
    state: GameState


DEFAULT_COMBOS: tuple[WeightCombo, ...] = (
    WeightCombo(0, 1),
    WeightCombo(0, 2),
    WeightCombo(1, 0),
    WeightCombo(1, 3),
    WeightCombo(2, 1),
    WeightCombo(3, 0),
    WeightCombo(3, 1),
    WeightCombo(4, 1),
    WeightCombo(5, 1),
)


def build_level_config(level_id: str):
    level = next((item for item in CAMPAIGN_LEVELS if item.level_id == level_id), None)
    if level is None:
        raise ValueError(f"Unbekanntes level_id: {level_id}")
    return build_game_config(
        layout_name=level.layout_name,
        hazard_density=level.hazard_density,
        hazard_count=level.hazard_count,
        starting_hp=level.starting_hp,
        turn_limit=level.turn_limit,
        enemy_turns_per_round=level.enemy_turns_per_round,
        enemy_route_cutoff_weight=level.enemy_route_cutoff_weight,
        enemy_chase_weight=level.enemy_chase_weight,
        score_balance=level.score_balance,
    )


def parse_combos(raw_values: list[str] | None) -> list[WeightCombo]:
    if not raw_values:
        return list(DEFAULT_COMBOS)

    combos: list[WeightCombo] = []
    for raw in raw_values:
        token = raw.strip()
        if not token:
            continue
        try:
            route_raw, chase_raw = token.split(":", maxsplit=1)
            route = int(route_raw)
            chase = int(chase_raw)
        except ValueError as exc:
            raise ValueError(f"Ungueltige Gewichtskombi '{raw}'. Erwartet route:chase.") from exc
        if route < 0 or chase < 0:
            raise ValueError(f"Negative Gewichte sind ungueltig: {raw}")
        if route == 0 and chase == 0:
            raise ValueError("0:0 ist ungueltig. Mindestens ein Gewicht muss > 0 sein.")
        combo = WeightCombo(route, chase)
        if combo not in combos:
            combos.append(combo)

    if not combos:
        raise ValueError("Keine gueltigen Gewichtskombinationen angegeben.")
    return combos


def clone_state(state: GameState) -> GameState:
    return deepcopy(state)


def collect_route_snapshots(level_id: str, route_name: str) -> list[Snapshot]:
    level = next(item for item in CAMPAIGN_LEVELS if item.level_id == level_id)
    commands = get_route_regression_spec_for_outcome(level.layout_name, route_name).commands
    state = GameState(config=build_level_config(level_id))
    snapshots: list[Snapshot] = [
        Snapshot(
            snapshot_id=f"{level_id}-{route_name}-s00",
            level_id=level_id,
            layout_name=level.layout_name,
            route_name=route_name,
            route_step_index=0,
            route_commands_total=len(commands),
            source_command=None,
            state=clone_state(state),
        )
    ]

    for step_index, command in enumerate(commands, start=1):
        if state.status != "running":
            break
        process_input(state, command)
        snapshots.append(
            Snapshot(
                snapshot_id=f"{level_id}-{route_name}-s{step_index:02d}",
                level_id=level_id,
                layout_name=level.layout_name,
                route_name=route_name,
                route_step_index=step_index,
                route_commands_total=len(commands),
                source_command=command,
                state=clone_state(state),
            )
        )

    return snapshots


def choose_even_indices(total: int, count: int) -> list[int]:
    if count <= 0 or total <= 0:
        return []
    if count >= total:
        return list(range(total))
    if count == 1:
        return [total // 2]

    raw = [int(math.floor(i * (total - 1) / (count - 1))) for i in range(count)]
    seen: set[int] = set()
    indices: list[int] = []
    for value in raw:
        if value not in seen:
            indices.append(value)
            seen.add(value)

    cursor = 0
    while len(indices) < count:
        if cursor not in seen:
            indices.append(cursor)
            seen.add(cursor)
        cursor += 1

    indices.sort()
    return indices


def select_representative_snapshots(snapshot_count: int) -> list[Snapshot]:
    route_keys: tuple[tuple[str, str], ...] = (("L2", "win"), ("L2", "lose"), ("L3", "win"), ("L3", "lose"))
    route_snapshots: list[list[Snapshot]] = [collect_route_snapshots(level_id, route_name) for level_id, route_name in route_keys]

    base = snapshot_count // len(route_snapshots)
    remainder = snapshot_count % len(route_snapshots)

    selected: list[Snapshot] = []
    for route_index, snapshots in enumerate(route_snapshots):
        take = base + (1 if route_index < remainder else 0)
        if take == 0:
            continue
        indices = choose_even_indices(total=len(snapshots), count=take)
        selected.extend(snapshots[index] for index in indices)

    if len(selected) < snapshot_count:
        spillover: list[Snapshot] = []
        for snapshots in route_snapshots:
            spillover.extend(snapshots)
        used_ids = {item.snapshot_id for item in selected}
        for candidate in spillover:
            if len(selected) >= snapshot_count:
                break
            if candidate.snapshot_id in used_ids:
                continue
            selected.append(candidate)
            used_ids.add(candidate.snapshot_id)

    return selected[:snapshot_count]


def compute_candidate_rows(state: GameState, combo: WeightCombo) -> list[dict[str, object]]:
    state_for_eval = clone_state(state)
    state_for_eval.config = replace(
        state_for_eval.config,
        enemy_route_cutoff_weight=combo.route_cutoff,
        enemy_chase_weight=combo.chase,
    )

    route_zone = build_extraction_route_zone(state_for_eval)
    control_keys = build_enemy_control_keys(state_for_eval)
    candidates = list_enemy_step_candidates(state_for_eval)

    rows: list[dict[str, object]] = []
    for index, pos in enumerate(candidates):
        collision_priority = 0 if pos == state_for_eval.player_pos else 1
        chase_distance = manhattan_distance(pos, state_for_eval.player_pos)
        key_distance = distance_to_zone(pos, control_keys)
        route_distance = distance_to_zone(pos, route_zone)
        extraction_distance = manhattan_distance(pos, state_for_eval.config.extraction_pos)
        route_pressure_distance = route_distance if state_for_eval.extraction_active else route_distance + key_distance
        weighted_pressure = (combo.route_cutoff * route_pressure_distance) + (combo.chase * chase_distance)
        score = build_enemy_step_score(
            state_for_eval,
            pos,
            index,
            route_zone=route_zone,
            control_keys=control_keys,
        )

        rows.append(
            {
                "pos": pos,
                "index": index,
                "collision_priority": collision_priority,
                "chase_distance": chase_distance,
                "route_distance": route_distance,
                "key_distance": key_distance,
                "extraction_distance": extraction_distance,
                "route_pressure_distance": route_pressure_distance,
                "weighted_pressure": weighted_pressure,
                "score": score,
            }
        )

    return rows


def find_decisive_field(
    rows: list[dict[str, object]],
    field_names: tuple[str, ...],
) -> str:
    contenders = list(rows)
    for field_index, field_name in enumerate(field_names):
        min_value = min(int(item["score"][field_index]) for item in contenders)
        reduced = [item for item in contenders if int(item["score"][field_index]) == min_value]
        contenders = reduced
        if len(contenders) == 1:
            return field_name
    return "index"


def analyze_snapshot(snapshot: Snapshot, combos: list[WeightCombo]) -> dict[str, object]:
    combo_results: list[dict[str, object]] = []

    for combo in combos:
        rows = compute_candidate_rows(snapshot.state, combo)
        winner = min(rows, key=lambda item: item["score"])

        probe = clone_state(snapshot.state)
        probe.config = replace(
            probe.config,
            enemy_route_cutoff_weight=combo.route_cutoff,
            enemy_chase_weight=combo.chase,
        )
        expected = choose_enemy_step(probe)
        if expected != winner["pos"]:
            raise AssertionError(
                f"Analyse-Inkonsistenz fuer {snapshot.snapshot_id} @ {combo.label}: "
                f"expected {expected}, calculated {winner['pos']}"
            )

        score_fields = enemy_step_score_fields(probe)
        decisive_field = find_decisive_field(
            rows,
            field_names=score_fields,
        )
        combo_results.append(
            {
                "combo": {
                    "route_cutoff": combo.route_cutoff,
                    "chase": combo.chase,
                    "label": combo.label,
                },
                "chosen_step": winner["pos"],
                "decisive_field": decisive_field,
                "score_fields": score_fields,
                "chosen_weighted_pressure": winner["weighted_pressure"],
                "candidates": [
                    {
                        "pos": row["pos"],
                        "index": row["index"],
                        "collision_priority": row["collision_priority"],
                        "weighted_pressure": row["weighted_pressure"],
                        "route_pressure_distance": row["route_pressure_distance"],
                        "route_distance": row["route_distance"],
                        "chase_distance": row["chase_distance"],
                        "key_distance": row["key_distance"],
                        "extraction_distance": row["extraction_distance"],
                        "score": row["score"],
                    }
                    for row in rows
                ],
            }
        )

    unique_steps = sorted({tuple(item["chosen_step"]) for item in combo_results})
    sensitive = len(unique_steps) > 1
    decisive_fields = {str(item["decisive_field"]) for item in combo_results}

    plateau_reason = None
    if not sensitive:
        if decisive_fields == {"collision_priority"}:
            plateau_reason = "collision_priority_fixiert_spielerfang"
        elif decisive_fields == {"weighted_pressure"}:
            plateau_reason = "weighted_pressure_hat_stabiles_minimum"
        elif "weighted_pressure" not in decisive_fields:
            if "index" in decisive_fields:
                plateau_reason = "tie_break_bis_kandidatenindex"
            else:
                plateau_reason = "sekundaere_tie_breaker_route_chase_key"
        else:
            plateau_reason = "gemischte_gewicht_und_tie_break_effekte"

    return {
        "snapshot_id": snapshot.snapshot_id,
        "level_id": snapshot.level_id,
        "layout_name": snapshot.layout_name,
        "route_name": snapshot.route_name,
        "route_step_index": snapshot.route_step_index,
        "route_commands_total": snapshot.route_commands_total,
        "source_command": snapshot.source_command,
        "player_pos": snapshot.state.player_pos,
        "enemy_pos": snapshot.state.enemy_pos,
        "hp": snapshot.state.hp,
        "turns_left": snapshot.state.turns_left,
        "collected_cells": len(snapshot.state.collected_cells),
        "extraction_active": snapshot.state.extraction_active,
        "status": snapshot.state.status,
        "chosen_steps_by_combo": {
            item["combo"]["label"]: item["chosen_step"]
            for item in combo_results
        },
        "combo_results": combo_results,
        "unique_chosen_steps": unique_steps,
        "sensitive_to_weights": sensitive,
        "plateau_reason": plateau_reason,
    }


def build_summary(results: list[dict[str, object]], combos: list[WeightCombo]) -> dict[str, object]:
    plateau_results = [item for item in results if not bool(item["sensitive_to_weights"])]
    sensitive_results = [item for item in results if bool(item["sensitive_to_weights"])]

    plateau_by_reason: dict[str, int] = {}
    decisive_histogram: dict[str, int] = {}
    for item in results:
        reason = item.get("plateau_reason")
        if reason:
            plateau_by_reason[reason] = plateau_by_reason.get(reason, 0) + 1
        for combo_result in item["combo_results"]:
            decisive = str(combo_result["decisive_field"])
            decisive_histogram[decisive] = decisive_histogram.get(decisive, 0) + 1

    combo_action_diversity: dict[str, int] = {combo.label: 0 for combo in combos}
    for combo in combos:
        unique_steps = {tuple(item["chosen_steps_by_combo"][combo.label]) for item in results}
        combo_action_diversity[combo.label] = len(unique_steps)

    return {
        "snapshot_count": len(results),
        "sensitive_snapshot_count": len(sensitive_results),
        "plateau_snapshot_count": len(plateau_results),
        "sensitivity_rate_pct": round((len(sensitive_results) / len(results)) * 100.0, 3) if results else 0.0,
        "plateau_by_reason": dict(sorted(plateau_by_reason.items())),
        "decisive_field_histogram": dict(sorted(decisive_histogram.items())),
        "combo_action_diversity": combo_action_diversity,
    }


def format_pos(pos: tuple[int, int]) -> str:
    return f"({pos[0]},{pos[1]})"


def write_markdown_report(path: Path, report: dict[str, object], combos: list[WeightCombo]) -> None:
    combo_labels = [combo.label for combo in combos]
    lines: list[str] = []
    lines.append("# Enemy-Step-Sensitivitaetsanalyse (TASK-023)")
    lines.append("")
    lines.append("## Setup")
    lines.append(f"- Snapshot-Anzahl: {report['snapshot_count']}")
    lines.append("- Levels: L2 (corridor), L3 (crossfire)")
    lines.append("- Routenquellen: route_regression_specs (win + lose)")
    lines.append(f"- Gewichtskombinationen: {', '.join(combo_labels)}")
    lines.append("")

    summary = report["summary"]
    lines.append("## Summary")
    lines.append(f"- Sensitive Snapshots: {summary['sensitive_snapshot_count']} von {summary['snapshot_count']}")
    lines.append(f"- Plateau-Snapshots: {summary['plateau_snapshot_count']} von {summary['snapshot_count']}")
    lines.append(f"- Sensitivity-Rate: {summary['sensitivity_rate_pct']}%")
    lines.append(f"- Plateau-Ursachen: {json.dumps(summary['plateau_by_reason'], ensure_ascii=True)}")
    lines.append(f"- Decisive-Field-Histogramm: {json.dumps(summary['decisive_field_histogram'], ensure_ascii=True)}")
    lines.append("")

    lines.append("## Snapshot-Matrix")
    header = [
        "snapshot_id",
        "level",
        "route",
        "step",
        "player",
        "enemy",
        "extract",
        *combo_labels,
        "sensitive",
        "plateau_reason",
    ]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    for item in report["snapshots"]:
        row = [
            str(item["snapshot_id"]),
            str(item["level_id"]),
            str(item["route_name"]),
            str(item["route_step_index"]),
            format_pos(tuple(item["player_pos"])),
            format_pos(tuple(item["enemy_pos"])),
            "Y" if bool(item["extraction_active"]) else "N",
        ]
        for label in combo_labels:
            row.append(format_pos(tuple(item["chosen_steps_by_combo"][label])))
        row.append("Y" if bool(item["sensitive_to_weights"]) else "N")
        row.append(str(item["plateau_reason"] or ""))
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Hinweise")
    lines.append("- `sensitive=Y`: Mindestens zwei Gewichtskombinationen waehlen unterschiedliche Enemy-Schritte.")
    lines.append("- `plateau_reason`: Kompakte Ursache fuer fehlende Sensitivitaet pro Snapshot.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analysiert choose_enemy_step auf Gewichtssensitivitaet fuer L2/L3-Snapshots."
    )
    parser.add_argument(
        "--snapshot-count",
        type=int,
        default=20,
        help="Anzahl repraesentativer Snapshots (Default: 20).",
    )
    parser.add_argument(
        "--combo",
        action="append",
        default=None,
        help="Gewichtskombination route:chase (mehrfach nutzbar).",
    )
    parser.add_argument(
        "--output-json",
        required=True,
        help="Pfad fuer den JSON-Report.",
    )
    parser.add_argument(
        "--output-md",
        required=True,
        help="Pfad fuer den Markdown-Report.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="JSON-Report zusaetzlich auf stdout ausgeben.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.snapshot_count < 20:
        raise ValueError("snapshot-count muss mindestens 20 sein, um TASK-023 abzudecken.")

    combos = parse_combos(args.combo)
    snapshots = select_representative_snapshots(snapshot_count=args.snapshot_count)

    results = [analyze_snapshot(snapshot=item, combos=combos) for item in snapshots]
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_count": len(results),
        "combos": [
            {
                "route_cutoff": combo.route_cutoff,
                "chase": combo.chase,
                "label": combo.label,
            }
            for combo in combos
        ],
        "snapshots": results,
        "summary": build_summary(results=results, combos=combos),
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    write_markdown_report(output_md, report=report, combos=combos)

    if args.stdout:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print(f"JSON-Report geschrieben: {output_json}")
        print(f"Markdown-Report geschrieben: {output_md}")
        print(f"Sensitive Snapshots: {report['summary']['sensitive_snapshot_count']} / {report['summary']['snapshot_count']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
