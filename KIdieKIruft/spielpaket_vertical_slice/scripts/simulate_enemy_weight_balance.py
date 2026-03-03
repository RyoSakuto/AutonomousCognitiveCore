#!/usr/bin/env python3
"""Offline-balancing runner for enemy heuristic weights."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from game.vertical_slice import (  # noqa: E402
    CAMPAIGN_LEVELS,
    MOVE_MAP,
    GameConfig,
    GameState,
    build_game_config,
    manhattan_distance,
    process_input,
)


@dataclass(frozen=True)
class WeightCombo:
    route_cutoff: int
    chase: int


@dataclass(frozen=True)
class EpisodeMetrics:
    won: bool
    turns_used: int
    hp_loss: float
    enemy_collisions: int


@dataclass(frozen=True)
class AggregateMetrics:
    level_id: str
    layout_name: str
    enemy_turns_per_round: int
    route_cutoff: int
    chase: int
    runs: int
    win_rate_pct: float
    avg_turns_used: float
    avg_hp_loss: float
    avg_enemy_collisions: float


def parse_combos(raw_values: list[str]) -> list[WeightCombo]:
    combos: list[WeightCombo] = []
    for raw in raw_values:
        token = raw.strip()
        if not token:
            continue
        try:
            route_raw, chase_raw = token.split(":", maxsplit=1)
            route_value = int(route_raw)
            chase_value = int(chase_raw)
        except ValueError as exc:
            raise ValueError(f"Ungueltige combo '{raw}'. Erwarte Format route:chase, z. B. 2:1") from exc
        if route_value < 0 or chase_value < 0:
            raise ValueError(f"Gewichte duerfen nicht negativ sein: {raw}")
        if route_value == 0 and chase_value == 0:
            raise ValueError("Mindestens ein Gewicht muss groesser als 0 sein (0:0 ist ungueltig).")
        combo = WeightCombo(route_cutoff=route_value, chase=chase_value)
        if combo not in combos:
            combos.append(combo)
    if not combos:
        raise ValueError("Keine gueltigen Gewichtungs-Kombinationen angegeben.")
    return combos


def clone_state(state: GameState) -> GameState:
    return deepcopy(state)


def active_targets(state: GameState) -> tuple[tuple[int, int], ...]:
    if state.extraction_active or len(state.collected_cells) == len(state.config.energy_cells):
        return (state.config.extraction_pos,)
    return tuple(sorted(state.config.energy_cells - state.collected_cells))


def distance_to_targets(state: GameState) -> int:
    targets = active_targets(state)
    if not targets:
        return 0
    return min(manhattan_distance(state.player_pos, target) for target in targets)


def score_candidate(
    current: GameState,
    candidate: GameState,
    command: str,
    visit_counts: dict[tuple[int, int], int],
) -> float:
    if candidate.status == "win":
        return 2_000_000.0
    if candidate.status == "lose":
        return -2_000_000.0

    previous_distance = distance_to_targets(current)
    new_distance = distance_to_targets(candidate)
    progress = previous_distance - new_distance

    score = 0.0
    score += progress * 75.0
    score -= new_distance * 18.0

    score += (len(candidate.collected_cells) - len(current.collected_cells)) * 420.0
    if candidate.extraction_active and not current.extraction_active:
        score += 480.0

    hp_delta = current.hp - candidate.hp
    score -= hp_delta * 440.0

    if "[GEGNER] Kollision!" in candidate.last_message:
        score -= 260.0
    if "[GEFAHR]" in candidate.last_message:
        score -= 160.0

    enemy_distance = manhattan_distance(candidate.player_pos, candidate.enemy_pos)
    score += enemy_distance * 2.5

    score -= visit_counts.get(candidate.player_pos, 0) * 18.0

    dx, dy = MOVE_MAP[command]
    expected_target = (current.player_pos[0] + dx, current.player_pos[1] + dy)
    if not (0 <= expected_target[0] < current.config.width and 0 <= expected_target[1] < current.config.height):
        score -= 80.0
    if candidate.player_pos == current.player_pos:
        score -= 50.0

    return score


def rollout_value(
    state: GameState,
    depth: int,
    visit_counts: dict[tuple[int, int], int],
) -> float:
    if state.status == "win":
        return 2_000_000.0
    if state.status == "lose":
        return -2_000_000.0
    if depth <= 0:
        return 0.0

    best_score = float("-inf")
    for command in MOVE_MAP:
        probe = clone_state(state)
        process_input(probe, command)
        local_score = score_candidate(state, probe, command, visit_counts=visit_counts)
        if depth > 1 and probe.status == "running":
            child_visits = dict(visit_counts)
            child_visits[probe.player_pos] = child_visits.get(probe.player_pos, 0) + 1
            local_score += 0.68 * rollout_value(probe, depth - 1, visit_counts=child_visits)
        if local_score > best_score:
            best_score = local_score
    return best_score


def choose_command(
    state: GameState,
    rng: random.Random,
    mistake_rate: float,
    noise: float,
    lookahead_depth: int,
    visit_counts: dict[tuple[int, int], int],
) -> str:
    commands = tuple(MOVE_MAP)
    if rng.random() < mistake_rate:
        return rng.choice(commands)

    best_command = commands[0]
    best_score = float("-inf")
    for command in commands:
        probe = clone_state(state)
        process_input(probe, command)
        score = score_candidate(state, probe, command, visit_counts=visit_counts)
        if lookahead_depth > 1 and probe.status == "running":
            child_visits = dict(visit_counts)
            child_visits[probe.player_pos] = child_visits.get(probe.player_pos, 0) + 1
            score += 0.68 * rollout_value(probe, lookahead_depth - 1, visit_counts=child_visits)
        if noise > 0:
            score += rng.uniform(-noise, noise)
        if score > best_score:
            best_score = score
            best_command = command
    return best_command


def run_episode(
    config: GameConfig,
    seed: int,
    mistake_rate: float,
    noise: float,
    lookahead_depth: int,
) -> EpisodeMetrics:
    rng = random.Random(seed)
    state = GameState(config=config)
    collision_count = 0
    visit_counts: dict[tuple[int, int], int] = defaultdict(int)
    visit_counts[state.player_pos] += 1

    while state.status == "running":
        command = choose_command(
            state,
            rng=rng,
            mistake_rate=mistake_rate,
            noise=noise,
            lookahead_depth=lookahead_depth,
            visit_counts=visit_counts,
        )
        process_input(state, command)
        collision_count += state.last_message.count("[GEGNER] Kollision!")
        visit_counts[state.player_pos] += 1

    turns_used = config.turn_limit - state.turns_left
    capped_hp = max(0, min(config.starting_hp, state.hp))
    hp_loss = float(config.starting_hp - capped_hp)

    return EpisodeMetrics(
        won=state.status == "win",
        turns_used=turns_used,
        hp_loss=hp_loss,
        enemy_collisions=collision_count,
    )


def aggregate_level_combo(
    level_id: str,
    layout_name: str,
    enemy_turns_per_round: int,
    combo: WeightCombo,
    episodes: list[EpisodeMetrics],
) -> AggregateMetrics:
    wins = sum(1 for episode in episodes if episode.won)
    runs = len(episodes)
    return AggregateMetrics(
        level_id=level_id,
        layout_name=layout_name,
        enemy_turns_per_round=enemy_turns_per_round,
        route_cutoff=combo.route_cutoff,
        chase=combo.chase,
        runs=runs,
        win_rate_pct=(wins / runs) * 100.0,
        avg_turns_used=mean(episode.turns_used for episode in episodes),
        avg_hp_loss=mean(episode.hp_loss for episode in episodes),
        avg_enemy_collisions=mean(episode.enemy_collisions for episode in episodes),
    )


def run_balancing(
    runs_per_combo: int,
    base_seed: int,
    mistake_rate: float,
    noise: float,
    lookahead_depth: int,
    combos: list[WeightCombo],
) -> list[AggregateMetrics]:
    results: list[AggregateMetrics] = []

    for level_index, level in enumerate(CAMPAIGN_LEVELS):
        for combo in combos:
            config = build_game_config(
                layout_name=level.layout_name,
                hazard_density=level.hazard_density,
                hazard_count=level.hazard_count,
                starting_hp=level.starting_hp,
                turn_limit=level.turn_limit,
                enemy_turns_per_round=level.enemy_turns_per_round,
                enemy_route_cutoff_weight=combo.route_cutoff,
                enemy_chase_weight=combo.chase,
                score_balance=level.score_balance,
            )
            episodes: list[EpisodeMetrics] = []
            for run_index in range(runs_per_combo):
                seed = base_seed + (level_index * 100_000) + run_index
                episodes.append(
                    run_episode(
                        config,
                        seed=seed,
                        mistake_rate=mistake_rate,
                        noise=noise,
                        lookahead_depth=lookahead_depth,
                    )
                )
            results.append(
                aggregate_level_combo(
                    level_id=level.level_id,
                    layout_name=level.layout_name,
                    enemy_turns_per_round=level.enemy_turns_per_round,
                    combo=combo,
                    episodes=episodes,
                )
            )
    return results


def format_markdown_table(results: list[AggregateMetrics]) -> str:
    lines = [
        "| Level | Layout | Gegnerzuege | route_cutoff | chase | Runs | Win-Rate | Avg Zuege | Avg HP-Verlust | Avg Kollisionen |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.level_id,
                    row.layout_name,
                    str(row.enemy_turns_per_round),
                    str(row.route_cutoff),
                    str(row.chase),
                    str(row.runs),
                    f"{row.win_rate_pct:.1f}%",
                    f"{row.avg_turns_used:.2f}",
                    f"{row.avg_hp_loss:.2f}",
                    f"{row.avg_enemy_collisions:.2f}",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def recommend_combo(
    level_id: str,
    rows: list[AggregateMetrics],
    baseline: WeightCombo,
) -> AggregateMetrics:
    target_winrate = {
        "L1": 82.0,
        "L2": 66.0,
        "L3": 58.0,
    }.get(level_id, 65.0)
    prefer_more_route_pressure = level_id == "L3"

    def score(row: AggregateMetrics) -> tuple[float, float, float, float, int, int]:
        core = (
            abs(row.win_rate_pct - target_winrate),
            row.avg_hp_loss,
            row.avg_enemy_collisions,
            row.avg_turns_used,
        )
        if prefer_more_route_pressure:
            return (
                *core,
                -row.route_cutoff,
                abs(row.chase - baseline.chase),
            )
        distance_to_baseline = (
            abs(row.route_cutoff - baseline.route_cutoff)
            + abs(row.chase - baseline.chase)
        )
        route_tiebreak = -row.route_cutoff if level_id != "L1" else row.route_cutoff
        return (
            *core,
            distance_to_baseline,
            route_tiebreak,
        )

    return min(rows, key=score)


def as_jsonable(results: list[AggregateMetrics]) -> list[dict[str, object]]:
    return [
        {
            "level_id": row.level_id,
            "layout_name": row.layout_name,
            "enemy_turns_per_round": row.enemy_turns_per_round,
            "route_cutoff": row.route_cutoff,
            "chase": row.chase,
            "runs": row.runs,
            "win_rate_pct": round(row.win_rate_pct, 3),
            "avg_turns_used": round(row.avg_turns_used, 3),
            "avg_hp_loss": round(row.avg_hp_loss, 3),
            "avg_enemy_collisions": round(row.avg_enemy_collisions, 3),
        }
        for row in results
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline-Balancing fuer route_cutoff/chase-Gewichte.")
    parser.add_argument("--runs", type=int, default=240, help="Simulationen pro Level+Kombination (Default: 240)")
    parser.add_argument("--seed", type=int, default=20260214, help="Basis-Seed fuer reproduzierbare Laeufe")
    parser.add_argument("--mistake-rate", type=float, default=0.16, help="Wahrscheinlichkeit fuer einen fehlerhaften Zufallszug")
    parser.add_argument("--noise", type=float, default=1.1, help="Rauschanteil fuer die Aktionswahl")
    parser.add_argument("--lookahead-depth", type=int, default=2, help="Lookahead-Tiefe fuer Agentenplanung (Default: 2)")
    parser.add_argument(
        "--combo",
        action="append",
        default=[],
        help="Gewichtskombination im Format route:chase (mehrfach nutzbar).",
    )
    parser.add_argument("--json-out", type=Path, default=None, help="Optionaler JSON-Exportpfad.")
    parser.add_argument("--md-out", type=Path, default=None, help="Optionaler Markdown-Exportpfad.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    combo_tokens = args.combo or ["0:1", "1:1", "2:1", "3:1", "2:2", "3:2", "4:1"]
    combos = parse_combos(combo_tokens)
    results = run_balancing(
        runs_per_combo=args.runs,
        base_seed=args.seed,
        mistake_rate=args.mistake_rate,
        noise=args.noise,
        lookahead_depth=max(1, args.lookahead_depth),
        combos=combos,
    )

    level_order = {level.level_id: index for index, level in enumerate(CAMPAIGN_LEVELS)}
    results.sort(key=lambda row: (level_order[row.level_id], row.route_cutoff, row.chase))

    markdown_table = format_markdown_table(results)
    print(markdown_table)

    by_level: dict[str, list[AggregateMetrics]] = {}
    for row in results:
        by_level.setdefault(row.level_id, []).append(row)
    baseline_by_level = {
        level.level_id: WeightCombo(
            route_cutoff=level.enemy_route_cutoff_weight,
            chase=level.enemy_chase_weight,
        )
        for level in CAMPAIGN_LEVELS
    }

    print("\nEmpfohlene Kombinationen:")
    for level in CAMPAIGN_LEVELS:
        baseline = baseline_by_level[level.level_id]
        choice = recommend_combo(level.level_id, by_level[level.level_id], baseline=baseline)
        print(
            f"- {level.level_id} ({level.layout_name}): "
            f"route_cutoff={choice.route_cutoff}, chase={choice.chase} "
            f"(Win-Rate {choice.win_rate_pct:.1f}%, HP-Verlust {choice.avg_hp_loss:.2f}, "
            f"Delta route {choice.route_cutoff - baseline.route_cutoff:+d}, "
            f"Delta chase {choice.chase - baseline.chase:+d})"
        )

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(f"{json.dumps(as_jsonable(results), indent=2, ensure_ascii=True)}\n", encoding="utf-8")

    if args.md_out is not None:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(f"{markdown_table}\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
