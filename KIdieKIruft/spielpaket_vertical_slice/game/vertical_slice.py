#!/usr/bin/env python3
"""Minimal playable vertical slice in pure Python (no dependencies)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable


Position = tuple[int, int]
QUIT_COMMANDS = frozenset({"q", "quit", "exit"})
RESTART_COMMANDS = frozenset({"r", "restart"})
EVENT_SEPARATOR = " | "
SAVE_FILE_NAME = "meta_progression.json"
SAVE_FILE_VERSION = 1

@dataclass(frozen=True)
class LevelLayout:
    name: str
    description: str
    width: int
    height: int
    start_pos: Position
    enemy_start_pos: Position
    extraction_pos: Position
    energy_cells: tuple[Position, ...]
    hazard_candidates: tuple[Position, ...]
    base_hazard_count: int
    turn_limit: int = 14


@dataclass(frozen=True)
class CampaignLevelDefinition:
    level_id: str
    layout_name: str
    starting_hp: int
    turn_limit: int
    hazard_density: str
    hazard_count: int
    enemy_turns_per_round: int
    enemy_route_cutoff_weight: int
    enemy_chase_weight: int
    score_balance: "ScoreBalance"


@dataclass(frozen=True)
class ScoreBalance:
    turn_reward: int
    energy_cell_reward: int
    extraction_activation_reward: int
    hazard_damage_penalty: int
    enemy_collision_penalty: int
    level_win_base_reward: int
    level_win_hp_bonus: int
    level_win_turn_bonus: int


@dataclass(frozen=True)
class StartMenuSelection:
    layout_name: str
    hazard_density: str


class ScoreBalanceConfigError(ValueError):
    """Raised when the external score-balance config is missing or invalid."""


SCORE_BALANCE_FILE_NAME = "score_balance_profiles.json"
SCORE_BALANCE_SCHEMA_VERSION = 1
SCORE_BALANCE_REQUIRED_LEVELS: tuple[str, ...] = ("L1", "L2", "L3")
SCORE_BALANCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "turn_reward",
    "energy_cell_reward",
    "extraction_activation_reward",
    "hazard_damage_penalty",
    "enemy_collision_penalty",
    "level_win_base_reward",
    "level_win_hp_bonus",
    "level_win_turn_bonus",
)
SCORE_BALANCE_STRICT_POSITIVE_FIELDS = frozenset(
    {
        "turn_reward",
        "energy_cell_reward",
        "extraction_activation_reward",
        "level_win_base_reward",
    }
)
DEFAULT_SCORE_BALANCE_PROFILE_VALUES: dict[str, dict[str, int]] = {
    "L1": {
        "turn_reward": 12,
        "energy_cell_reward": 120,
        "extraction_activation_reward": 160,
        "hazard_damage_penalty": 24,
        "enemy_collision_penalty": 36,
        "level_win_base_reward": 220,
        "level_win_hp_bonus": 42,
        "level_win_turn_bonus": 22,
    },
    "L2": {
        "turn_reward": 10,
        "energy_cell_reward": 130,
        "extraction_activation_reward": 185,
        "hazard_damage_penalty": 30,
        "enemy_collision_penalty": 44,
        "level_win_base_reward": 270,
        "level_win_hp_bonus": 38,
        "level_win_turn_bonus": 18,
    },
    "L3": {
        "turn_reward": 8,
        "energy_cell_reward": 145,
        "extraction_activation_reward": 210,
        "hazard_damage_penalty": 36,
        "enemy_collision_penalty": 52,
        "level_win_base_reward": 320,
        "level_win_hp_bonus": 34,
        "level_win_turn_bonus": 15,
    },
}


def resolve_score_balance_profiles_path(score_balance_file: str | Path | None = None) -> Path:
    if score_balance_file is not None:
        return Path(score_balance_file)
    return Path(__file__).resolve().with_name(SCORE_BALANCE_FILE_NAME)


def _parse_score_balance_profile(level_id: str, payload: object, source: str) -> ScoreBalance:
    if not isinstance(payload, dict):
        raise ScoreBalanceConfigError(
            f"{source}: Profil '{level_id}' muss ein JSON-Objekt sein."
        )

    missing_fields = [field for field in SCORE_BALANCE_REQUIRED_FIELDS if field not in payload]
    if missing_fields:
        raise ScoreBalanceConfigError(
            f"{source}: Pflichtfeld fehlt in '{level_id}': {missing_fields[0]}."
        )

    unknown_fields = sorted(set(payload) - set(SCORE_BALANCE_REQUIRED_FIELDS))
    if unknown_fields:
        raise ScoreBalanceConfigError(
            f"{source}: Unbekanntes Feld in '{level_id}': {unknown_fields[0]}."
        )

    values: dict[str, int] = {}
    for field_name in SCORE_BALANCE_REQUIRED_FIELDS:
        raw_value = payload[field_name]
        if not isinstance(raw_value, int) or isinstance(raw_value, bool):
            raise ScoreBalanceConfigError(
                f"{source}: Feld '{level_id}.{field_name}' muss eine ganze Zahl sein."
            )
        if raw_value < 0:
            raise ScoreBalanceConfigError(
                f"{source}: Feld '{level_id}.{field_name}' darf nicht negativ sein."
            )
        if field_name in SCORE_BALANCE_STRICT_POSITIVE_FIELDS and raw_value <= 0:
            raise ScoreBalanceConfigError(
                f"{source}: Feld '{level_id}.{field_name}' muss groesser als 0 sein."
            )
        values[field_name] = raw_value

    return ScoreBalance(**values)


def _parse_score_balance_payload(payload: object, source: str) -> dict[str, ScoreBalance]:
    if not isinstance(payload, dict):
        raise ScoreBalanceConfigError(
            f"{source}: Top-Level muss ein JSON-Objekt sein."
        )

    version = payload.get("version")
    if version != SCORE_BALANCE_SCHEMA_VERSION:
        raise ScoreBalanceConfigError(
            f"{source}: Feld 'version' muss {SCORE_BALANCE_SCHEMA_VERSION} sein."
        )

    profiles_payload = payload.get("profiles")
    if not isinstance(profiles_payload, dict):
        raise ScoreBalanceConfigError(
            f"{source}: Feld 'profiles' muss ein JSON-Objekt sein."
        )

    missing_levels = [level_id for level_id in SCORE_BALANCE_REQUIRED_LEVELS if level_id not in profiles_payload]
    if missing_levels:
        raise ScoreBalanceConfigError(
            f"{source}: Pflichtprofil fehlt: {missing_levels[0]}."
        )

    unknown_levels = sorted(set(profiles_payload) - set(SCORE_BALANCE_REQUIRED_LEVELS))
    if unknown_levels:
        raise ScoreBalanceConfigError(
            f"{source}: Unbekanntes Profil gefunden: {unknown_levels[0]}."
        )

    return {
        level_id: _parse_score_balance_profile(level_id, profiles_payload[level_id], source)
        for level_id in SCORE_BALANCE_REQUIRED_LEVELS
    }


def build_default_score_balance_profiles() -> dict[str, ScoreBalance]:
    return {
        level_id: ScoreBalance(**values)
        for level_id, values in DEFAULT_SCORE_BALANCE_PROFILE_VALUES.items()
    }


def load_score_balance_profiles(score_balance_file: str | Path | None = None) -> dict[str, ScoreBalance]:
    path = resolve_score_balance_profiles_path(score_balance_file)
    source = str(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ScoreBalanceConfigError(f"{source}: Datei nicht gefunden.") from exc
    except OSError as exc:
        raise ScoreBalanceConfigError(f"{source}: Datei konnte nicht gelesen werden ({exc}).") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScoreBalanceConfigError(
            f"{source}: JSON-Syntaxfehler ({exc.msg}) in Zeile {exc.lineno}, Spalte {exc.colno}."
        ) from exc

    return _parse_score_balance_payload(payload, source=source)


def load_score_balance_profiles_with_fallback(
    score_balance_file: str | Path | None = None,
    fallback_profiles: dict[str, ScoreBalance] | None = None,
) -> tuple[dict[str, ScoreBalance], str | None]:
    fallback = dict(fallback_profiles) if fallback_profiles is not None else build_default_score_balance_profiles()
    try:
        profiles = load_score_balance_profiles(score_balance_file=score_balance_file)
    except ScoreBalanceConfigError as exc:
        warning = f"{exc} Fallback-Profilwerte werden verwendet."
        return fallback, warning
    return profiles, None


AVAILABLE_LAYOUTS: dict[str, LevelLayout] = {
    "classic": LevelLayout(
        name="classic",
        description="Originales 5x5-Layout aus dem Vertical Slice.",
        width=5,
        height=5,
        start_pos=(0, 0),
        enemy_start_pos=(4, 0),
        extraction_pos=(4, 4),
        energy_cells=((1, 0), (2, 2), (4, 1)),
        hazard_candidates=((1, 1), (3, 3), (4, 0), (0, 3), (2, 4)),
        base_hazard_count=3,
    ),
    "corridor": LevelLayout(
        name="corridor",
        description="Schmaler Vorstoss von links unten nach rechts oben.",
        width=6,
        height=5,
        start_pos=(0, 4),
        enemy_start_pos=(5, 4),
        extraction_pos=(5, 0),
        energy_cells=((1, 4), (3, 2), (4, 1)),
        hazard_candidates=((1, 3), (2, 3), (3, 1), (4, 2), (5, 2), (2, 0)),
        base_hazard_count=3,
        turn_limit=16,
    ),
    "crossfire": LevelLayout(
        name="crossfire",
        description="Kreuzfeuer-Mitte mit riskanten Diagonalwegen.",
        width=5,
        height=6,
        start_pos=(2, 5),
        enemy_start_pos=(4, 5),
        extraction_pos=(2, 0),
        energy_cells=((0, 3), (2, 2), (4, 3)),
        hazard_candidates=((1, 4), (3, 4), (1, 1), (3, 1), (2, 3), (2, 1)),
        base_hazard_count=4,
        turn_limit=15,
    ),
}

HAZARD_DENSITY_FACTORS: dict[str, float] = {
    "low": 0.67,
    "normal": 1.0,
    "high": 1.34,
}

DEFAULT_SCORE_BALANCE_PROFILES = build_default_score_balance_profiles()
SCORE_BALANCE_PROFILES, SCORE_BALANCE_LOAD_WARNING = load_score_balance_profiles_with_fallback(
    fallback_profiles=DEFAULT_SCORE_BALANCE_PROFILES
)

CAMPAIGN_LEVELS: tuple[CampaignLevelDefinition, ...] = (
    CampaignLevelDefinition(
        level_id="L1",
        layout_name="classic",
        starting_hp=3,
        turn_limit=16,
        hazard_density="low",
        hazard_count=2,
        enemy_turns_per_round=1,
        enemy_route_cutoff_weight=0,
        enemy_chase_weight=1,
        score_balance=SCORE_BALANCE_PROFILES["L1"],
    ),
    CampaignLevelDefinition(
        level_id="L2",
        layout_name="corridor",
        starting_hp=10,
        turn_limit=14,
        hazard_density="normal",
        hazard_count=4,
        enemy_turns_per_round=2,
        enemy_route_cutoff_weight=2,
        enemy_chase_weight=1,
        score_balance=SCORE_BALANCE_PROFILES["L2"],
    ),
    CampaignLevelDefinition(
        level_id="L3",
        layout_name="crossfire",
        starting_hp=13,
        turn_limit=13,
        hazard_density="high",
        hazard_count=4,
        enemy_turns_per_round=2,
        enemy_route_cutoff_weight=4,
        enemy_chase_weight=1,
        score_balance=SCORE_BALANCE_PROFILES["L3"],
    ),
)

LAYOUT_SCORE_BALANCE: dict[str, ScoreBalance] = {
    level.layout_name: level.score_balance for level in CAMPAIGN_LEVELS
}


@dataclass(frozen=True)
class GameConfig:
    width: int = 5
    height: int = 5
    start_pos: Position = (0, 0)
    enemy_start_pos: Position = (4, 0)
    extraction_pos: Position = (4, 4)
    energy_cells: frozenset[Position] = frozenset({(1, 0), (2, 2), (4, 1)})
    hazard_tiles: frozenset[Position] = frozenset({(1, 1), (3, 3), (4, 0)})
    starting_hp: int = 3
    turn_limit: int = 14
    layout_name: str = "classic"
    hazard_density: str = "normal"
    enemy_contact_damage: int = 1
    enemy_turns_per_round: int = 1
    enemy_route_cutoff_weight: int = 0
    enemy_chase_weight: int = 1
    score_balance: ScoreBalance = field(default_factory=lambda: SCORE_BALANCE_PROFILES["L1"])


@dataclass
class GameState:
    config: GameConfig = field(default_factory=lambda: build_game_config())
    campaign_level_index: int = 1
    campaign_level_total: int = 1
    run_score: int = 0
    best_run_score: int = 0
    player_pos: Position = field(init=False)
    enemy_pos: Position = field(init=False)
    hp: int = field(init=False)
    turns_left: int = field(init=False)
    collected_cells: set[Position] = field(default_factory=set)
    extraction_active: bool = False
    status: str = "running"
    last_message: str = "[SYSTEM] Mission gestartet. Sammle 3 Energiezellen und erreiche die Extraktion."

    def __post_init__(self) -> None:
        self.player_pos = self.config.start_pos
        self.enemy_pos = self.config.enemy_start_pos
        self.hp = self.config.starting_hp
        self.turns_left = self.config.turn_limit

    @property
    def cells_remaining(self) -> int:
        return len(self.config.energy_cells) - len(self.collected_cells)


MOVE_MAP: dict[str, Position] = {
    "w": (0, -1),
    "a": (-1, 0),
    "s": (0, 1),
    "d": (1, 0),
}


def list_available_layouts() -> dict[str, str]:
    return {name: layout.description for name, layout in AVAILABLE_LAYOUTS.items()}


def normalize_hazard_density(value: str) -> str:
    density = value.strip().lower()
    if density not in HAZARD_DENSITY_FACTORS:
        valid = ", ".join(HAZARD_DENSITY_FACTORS)
        raise ValueError(f"Unbekannte Hazard-Dichte '{value}'. Erlaubt: {valid}")
    return density


def derive_hazard_tiles(
    layout: LevelLayout,
    hazard_density: str,
    hazard_count: int | None = None,
) -> frozenset[Position]:
    target_count = hazard_count
    if target_count is None:
        factor = HAZARD_DENSITY_FACTORS[hazard_density]
        target_count = int(round(layout.base_hazard_count * factor))
    target_count = max(0, target_count)
    target_count = min(len(layout.hazard_candidates), target_count)
    return frozenset(layout.hazard_candidates[:target_count])


def build_game_config(
    layout_name: str = "classic",
    hazard_density: str = "normal",
    hazard_count: int | None = None,
    starting_hp: int | None = None,
    turn_limit: int | None = None,
    enemy_turns_per_round: int = 1,
    enemy_route_cutoff_weight: int = 0,
    enemy_chase_weight: int = 1,
    score_balance: ScoreBalance | None = None,
) -> GameConfig:
    layout = AVAILABLE_LAYOUTS.get(layout_name)
    if layout is None:
        valid_layouts = ", ".join(sorted(AVAILABLE_LAYOUTS))
        raise ValueError(f"Unbekanntes Layout '{layout_name}'. Erlaubt: {valid_layouts}")

    if hazard_count is not None and hazard_count < 0:
        raise ValueError("hazard_count darf nicht negativ sein.")
    if starting_hp is not None and starting_hp <= 0:
        raise ValueError("starting_hp muss groesser als 0 sein.")

    if turn_limit is not None and turn_limit <= 0:
        raise ValueError("turn_limit muss groesser als 0 sein.")
    if enemy_turns_per_round <= 0:
        raise ValueError("enemy_turns_per_round muss groesser als 0 sein.")
    if enemy_route_cutoff_weight < 0:
        raise ValueError("enemy_route_cutoff_weight darf nicht negativ sein.")
    if enemy_chase_weight < 0:
        raise ValueError("enemy_chase_weight darf nicht negativ sein.")
    if enemy_route_cutoff_weight == 0 and enemy_chase_weight == 0:
        raise ValueError("Mindestens ein Heuristik-Gewicht muss groesser als 0 sein.")

    density = normalize_hazard_density(hazard_density)
    hazards = derive_hazard_tiles(layout, density, hazard_count=hazard_count)
    selected_score_balance = score_balance if score_balance is not None else LAYOUT_SCORE_BALANCE.get(layout.name, SCORE_BALANCE_PROFILES["L1"])
    return GameConfig(
        width=layout.width,
        height=layout.height,
        start_pos=layout.start_pos,
        enemy_start_pos=layout.enemy_start_pos,
        extraction_pos=layout.extraction_pos,
        energy_cells=frozenset(layout.energy_cells),
        hazard_tiles=hazards,
        starting_hp=starting_hp if starting_hp is not None else 3,
        turn_limit=turn_limit if turn_limit is not None else layout.turn_limit,
        layout_name=layout.name,
        hazard_density=density,
        enemy_turns_per_round=enemy_turns_per_round,
        enemy_route_cutoff_weight=enemy_route_cutoff_weight,
        enemy_chase_weight=enemy_chase_weight,
        score_balance=selected_score_balance,
    )


def build_campaign_configs(layout_name: str = "classic", hazard_density: str = "normal") -> tuple[GameConfig, ...]:
    if layout_name not in {level.layout_name for level in CAMPAIGN_LEVELS}:
        valid_layouts = ", ".join(level.layout_name for level in CAMPAIGN_LEVELS)
        raise ValueError(f"Unbekanntes Layout '{layout_name}'. Erlaubt: {valid_layouts}")

    density_override = normalize_hazard_density(hazard_density)
    ordered_layouts = tuple(level.layout_name for level in CAMPAIGN_LEVELS)
    start_index = ordered_layouts.index(layout_name)
    selected_levels = CAMPAIGN_LEVELS[start_index:]

    return tuple(
        build_game_config(
            layout_name=level.layout_name,
            hazard_density=level.hazard_density if density_override == "normal" else density_override,
            hazard_count=level.hazard_count,
            starting_hp=level.starting_hp,
            turn_limit=level.turn_limit,
            enemy_turns_per_round=level.enemy_turns_per_round,
            enemy_route_cutoff_weight=level.enemy_route_cutoff_weight,
            enemy_chase_weight=level.enemy_chase_weight,
            score_balance=level.score_balance,
        )
        for level in selected_levels
    )


def format_event(tag: str, message: str) -> str:
    return f"[{tag}] {message}"


def resolve_save_file_path(save_file: str | Path | None = None) -> Path:
    if save_file is not None:
        return Path(save_file)
    return Path(__file__).resolve().parents[1] / SAVE_FILE_NAME


def load_best_run_score(save_file: str | Path | None = None) -> tuple[int, str | None]:
    path = resolve_save_file_path(save_file)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0, None
    except OSError as exc:
        return 0, f"Save-Datei konnte nicht gelesen werden ({exc}). Best-Run = 0."

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0, "Save-Datei ist korrupt. Best-Run wurde auf 0 zurueckgesetzt."

    if not isinstance(payload, dict):
        return 0, "Save-Datei hat ungueltiges Format. Best-Run wurde auf 0 zurueckgesetzt."

    best_run_score = payload.get("best_run_score", 0)
    if not isinstance(best_run_score, int) or isinstance(best_run_score, bool) or best_run_score < 0:
        return 0, "Best-Run-Wert in Save-Datei ist ungueltig. Best-Run wurde auf 0 zurueckgesetzt."
    return best_run_score, None


def save_best_run_score(best_run_score: int, save_file: str | Path | None = None) -> str | None:
    path = resolve_save_file_path(save_file)
    safe_score = max(0, best_run_score)
    payload = {
        "version": SAVE_FILE_VERSION,
        "best_run_score": safe_score,
    }
    temp_path = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(f"{json.dumps(payload, ensure_ascii=True, indent=2)}\n", encoding="utf-8")
        temp_path.replace(path)
    except OSError as exc:
        return f"Best-Run konnte nicht gespeichert werden ({exc})."
    return None


def merge_events(*messages: str) -> str:
    return EVENT_SEPARATOR.join(message for message in messages if message)


def append_event(state: GameState, tag: str, message: str) -> None:
    state.last_message = merge_events(state.last_message, format_event(tag, message))


def add_score(state: GameState, delta: int) -> None:
    state.run_score = max(0, state.run_score + delta)


def is_restart_command(command: str) -> bool:
    return command.strip().lower() in RESTART_COMMANDS


def restart_game(
    previous_state: GameState | None = None,
    config: GameConfig | None = None,
    campaign_level_index: int | None = None,
    campaign_level_total: int | None = None,
    run_score: int | None = None,
    best_run_score: int | None = None,
    message: str = "Mission neu gestartet.",
) -> GameState:
    selected_config = config or (previous_state.config if previous_state is not None else build_game_config())
    selected_level_index = (
        campaign_level_index
        if campaign_level_index is not None
        else (previous_state.campaign_level_index if previous_state is not None else 1)
    )
    selected_level_total = (
        campaign_level_total
        if campaign_level_total is not None
        else (previous_state.campaign_level_total if previous_state is not None else 1)
    )
    selected_run_score = run_score if run_score is not None else (previous_state.run_score if previous_state is not None else 0)
    selected_best_run_score = (
        best_run_score if best_run_score is not None else (previous_state.best_run_score if previous_state is not None else 0)
    )
    state = GameState(
        config=selected_config,
        campaign_level_index=selected_level_index,
        campaign_level_total=selected_level_total,
        run_score=selected_run_score,
        best_run_score=selected_best_run_score,
    )
    state.last_message = format_event("SYSTEM", message)
    return state


def process_input(state: GameState, command: str) -> GameState:
    if state.status != "running":
        state.last_message = format_event("SYSTEM", "Mission ist bereits beendet. Nutze R fuer Neustart.")
        return state

    cmd = command.strip().lower()
    if cmd in QUIT_COMMANDS:
        state.status = "lose"
        state.last_message = format_event("MISSION", "Mission abgebrochen.")
        return state

    if cmd not in MOVE_MAP:
        state.last_message = format_event("INPUT", "Ungueltige Eingabe. Nutze W/A/S/D, R oder Q.")
        return state

    dx, dy = MOVE_MAP[cmd]
    nx = state.player_pos[0] + dx
    ny = state.player_pos[1] + dy

    if not is_inside(state.config, (nx, ny)):
        state.turns_left -= 1
        add_score(state, state.config.score_balance.turn_reward)
        messages = [
            format_event("AKTION", "Kante erreicht. Position bleibt unveraendert."),
            format_event("SYSTEM", "Zug verbraucht."),
        ]
        if state.hp > 0:
            apply_enemy_turn(state, messages)
        state.last_message = merge_events(*messages)
        evaluate_outcome(state)
        return state

    state.player_pos = (nx, ny)
    state.turns_left -= 1
    add_score(state, state.config.score_balance.turn_reward)

    total_cells = len(state.config.energy_cells)
    messages: list[str] = [format_event("AKTION", f"Bewegung zu {state.player_pos}.")]

    if state.player_pos in state.config.energy_cells and state.player_pos not in state.collected_cells:
        state.collected_cells.add(state.player_pos)
        add_score(state, state.config.score_balance.energy_cell_reward)
        messages.append(
            format_event(
                "FORTSCHRITT",
                f"Energiezelle gesichert ({len(state.collected_cells)}/{total_cells}).",
            )
        )

    if not state.extraction_active and state.cells_remaining == 0:
        state.extraction_active = True
        add_score(state, state.config.score_balance.extraction_activation_reward)
        messages.append(format_event("SYSTEM", "Extraktion aktiviert. Erreiche E."))

    if state.player_pos in state.config.hazard_tiles:
        state.hp -= 1
        add_score(state, -state.config.score_balance.hazard_damage_penalty)
        messages.append(format_event("GEFAHR", f"Schaden erhalten. HP jetzt {state.hp}."))

    if state.hp > 0:
        apply_enemy_turn(state, messages)

    state.last_message = merge_events(*messages)
    evaluate_outcome(state)
    return state


def apply_enemy_turn(state: GameState, messages: list[str]) -> None:
    total_enemy_turns = state.config.enemy_turns_per_round
    for turn_index in range(total_enemy_turns):
        previous_pos = state.enemy_pos
        state.enemy_pos = choose_enemy_step(state)
        turn_suffix = ""
        if total_enemy_turns > 1:
            turn_suffix = f" (Zug {turn_index + 1}/{total_enemy_turns})"

        if state.enemy_pos == previous_pos:
            messages.append(format_event("GEGNER", f"Gegner haelt Position bei {state.enemy_pos}{turn_suffix}."))
        else:
            messages.append(
                format_event(
                    "GEGNER",
                    f"Gegner bewegt sich von {previous_pos} zu {state.enemy_pos}{turn_suffix}.",
                )
            )

        if state.enemy_pos == state.player_pos:
            state.hp -= state.config.enemy_contact_damage
            add_score(
                state,
                -state.config.score_balance.enemy_collision_penalty * state.config.enemy_contact_damage,
            )
            messages.append(format_event("GEGNER", f"Kollision! Schaden erhalten. HP jetzt {state.hp}."))
            break


def manhattan_distance(a: Position, b: Position) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def distance_to_zone(pos: Position, zone: frozenset[Position]) -> int:
    if not zone:
        return 0
    return min(manhattan_distance(pos, target) for target in zone)


def build_enemy_control_keys(state: GameState) -> frozenset[Position]:
    remaining_cells = frozenset(state.config.energy_cells - state.collected_cells)
    if state.extraction_active or not remaining_cells:
        return frozenset(set(remaining_cells) | {state.config.extraction_pos})
    return remaining_cells


def build_manhattan_path(start: Position, end: Position, horizontal_first: bool) -> tuple[Position, ...]:
    x, y = start
    end_x, end_y = end
    path: list[Position] = [(x, y)]

    axes = ("x", "y") if horizontal_first else ("y", "x")
    for axis in axes:
        if axis == "x":
            while x != end_x:
                x += 1 if end_x > x else -1
                path.append((x, y))
        else:
            while y != end_y:
                y += 1 if end_y > y else -1
                path.append((x, y))
    return tuple(path)


def build_extraction_route_zone(state: GameState) -> frozenset[Position]:
    extraction = state.config.extraction_pos
    zone = set(build_manhattan_path(state.player_pos, extraction, horizontal_first=True))
    zone.update(build_manhattan_path(state.player_pos, extraction, horizontal_first=False))
    zone.add(extraction)
    ex, ey = extraction
    for neighbor in ((ex + 1, ey), (ex - 1, ey), (ex, ey + 1), (ex, ey - 1)):
        if is_inside(state.config, neighbor):
            zone.add(neighbor)
    return frozenset(zone)


def list_enemy_step_candidates(state: GameState) -> tuple[Position, ...]:
    enemy_x, enemy_y = state.enemy_pos
    player_x, player_y = state.player_pos
    ordered: list[Position] = []

    if enemy_x != player_x:
        ordered.append((enemy_x + (1 if player_x > enemy_x else -1), enemy_y))
    if enemy_y != player_y:
        ordered.append((enemy_x, enemy_y + (1 if player_y > enemy_y else -1)))

    for fallback in (
        (enemy_x + 1, enemy_y),
        (enemy_x - 1, enemy_y),
        (enemy_x, enemy_y - 1),
        (enemy_x, enemy_y + 1),
        (enemy_x, enemy_y),
    ):
        if fallback not in ordered:
            ordered.append(fallback)

    return tuple(pos for pos in ordered if is_inside(state.config, pos))


def prefers_route_tiebreak(state: GameState) -> bool:
    return state.config.enemy_route_cutoff_weight > state.config.enemy_chase_weight


def uses_soft_collision_tiebreak(state: GameState) -> bool:
    return (
        state.config.enemy_route_cutoff_weight > 0
        and state.enemy_pos == state.player_pos
    )


def enemy_step_score_fields(state: GameState) -> tuple[str, ...]:
    if state.config.enemy_route_cutoff_weight == 0:
        # Pure chase profile: avoid hidden route/key pressure tie-breaks in L1.
        return (
            "collision_priority",
            "weighted_pressure",
            "chase_distance",
            "index",
        )

    if state.extraction_active:
        if uses_soft_collision_tiebreak(state):
            return (
                "weighted_pressure",
                "route_distance",
                "chase_distance",
                "extraction_distance",
                "key_distance",
                "collision_priority",
                "index",
            )
        return (
            "collision_priority",
            "weighted_pressure",
            "route_distance",
            "chase_distance",
            "extraction_distance",
            "key_distance",
            "index",
        )

    if prefers_route_tiebreak(state):
        if uses_soft_collision_tiebreak(state):
            return (
                "weighted_pressure",
                "route_distance",
                "key_distance",
                "chase_distance",
                "extraction_distance",
                "collision_priority",
                "index",
            )
        return (
            "collision_priority",
            "weighted_pressure",
            "route_distance",
            "key_distance",
            "chase_distance",
            "extraction_distance",
            "index",
        )

    if uses_soft_collision_tiebreak(state):
        return (
            "weighted_pressure",
            "chase_distance",
            "key_distance",
            "route_distance",
            "extraction_distance",
            "collision_priority",
            "index",
        )
    return (
        "collision_priority",
        "weighted_pressure",
        "chase_distance",
        "key_distance",
        "route_distance",
        "extraction_distance",
        "index",
    )


def build_enemy_step_score(
    state: GameState,
    pos: Position,
    index: int,
    route_zone: frozenset[Position],
    control_keys: frozenset[Position],
) -> tuple[int, ...]:
    collision_priority = 0 if pos == state.player_pos else 1
    chase_distance = manhattan_distance(pos, state.player_pos)
    key_distance = distance_to_zone(pos, control_keys)
    route_distance = distance_to_zone(pos, route_zone)
    extraction_distance = manhattan_distance(pos, state.config.extraction_pos)

    if state.extraction_active:
        route_pressure_distance = route_distance
    else:
        route_pressure_distance = route_distance + key_distance

    weighted_pressure = (
        (state.config.enemy_route_cutoff_weight * route_pressure_distance)
        + (state.config.enemy_chase_weight * chase_distance)
    )

    score_components: dict[str, int] = {
        "collision_priority": collision_priority,
        "weighted_pressure": weighted_pressure,
        "route_distance": route_distance,
        "chase_distance": chase_distance,
        "extraction_distance": extraction_distance,
        "key_distance": key_distance,
        "index": index,
    }
    return tuple(score_components[field] for field in enemy_step_score_fields(state))


def choose_enemy_step(state: GameState) -> Position:
    route_zone = build_extraction_route_zone(state)
    control_keys = build_enemy_control_keys(state)
    candidates = list_enemy_step_candidates(state)
    scored_candidates: list[tuple[tuple[int, ...], Position]] = []

    for index, pos in enumerate(candidates):
        score = build_enemy_step_score(state, pos, index, route_zone=route_zone, control_keys=control_keys)

        scored_candidates.append((score, pos))

    if not scored_candidates:
        return state.enemy_pos
    return min(scored_candidates, key=lambda item: item[0])[1]


def is_inside(config: GameConfig, pos: Position) -> bool:
    x, y = pos
    return 0 <= x < config.width and 0 <= y < config.height


def evaluate_outcome(state: GameState) -> None:
    if state.hp <= 0:
        state.status = "lose"
        append_event(state, "MISSION", "Du bist ausgeschaltet.")
        return

    if state.extraction_active and state.player_pos == state.config.extraction_pos:
        state.status = "win"
        add_score(
            state,
            state.config.score_balance.level_win_base_reward
            + (state.hp * state.config.score_balance.level_win_hp_bonus)
            + (state.turns_left * state.config.score_balance.level_win_turn_bonus),
        )
        append_event(state, "MISSION", "Extraktion erfolgreich. Mission abgeschlossen.")
        return

    if state.turns_left <= 0:
        state.status = "lose"
        append_event(state, "MISSION", "Zeit abgelaufen.")
        return


def render(state: GameState) -> str:
    rows: list[str] = []
    for y in range(state.config.height):
        glyphs: list[str] = []
        for x in range(state.config.width):
            pos = (x, y)
            glyphs.append(tile_glyph(state, pos))
        rows.append(" ".join(glyphs))

    total_cells = len(state.config.energy_cells)
    extraction_state = "AKTIV (E)" if state.extraction_active else "GESPERRT (X)"
    hud = [
        "=== HUD ===",
        f"Kampagne    : Level {state.campaign_level_index}/{state.campaign_level_total}",
        f"Layout      : {state.config.layout_name}",
        f"Gefahren    : {state.config.hazard_density} ({len(state.config.hazard_tiles)} Felder)",
        f"Gegnerzug   : {state.config.enemy_turns_per_round}x pro Spielerzug",
        f"Heuristik   : Route x{state.config.enemy_route_cutoff_weight} / Chase x{state.config.enemy_chase_weight}",
        f"Score       : {state.run_score}",
        f"Best-Run    : {state.best_run_score}",
        f"HP          : {state.hp}/{state.config.starting_hp}",
        f"Zuege       : {state.turns_left}/{state.config.turn_limit}",
        f"Fortschritt : {len(state.collected_cells)}/{total_cells} Energiezellen",
        f"Extraktion  : {extraction_state}",
    ]
    return "\n".join(hud + ["", "=== KARTE ==="] + rows + ["", "=== EVENT ===", state.last_message])


def tile_glyph(state: GameState, pos: Position) -> str:
    if pos == state.player_pos:
        return "P"
    if pos == state.enemy_pos:
        return "G"
    if pos == state.config.extraction_pos:
        return "E" if state.extraction_active else "X"
    if pos in state.config.energy_cells and pos not in state.collected_cells:
        return "C"
    if pos in state.config.hazard_tiles:
        return "!"
    return "."


def _advance_campaign_level(
    state: GameState,
    campaign_configs: tuple[GameConfig, ...],
    current_level_index: int,
) -> tuple[GameState, int]:
    if state.status == "win" and current_level_index + 1 < len(campaign_configs):
        finished_level = current_level_index + 1
        next_level = current_level_index + 2
        return (
            restart_game(
                config=campaign_configs[current_level_index + 1],
                campaign_level_index=next_level,
                campaign_level_total=len(campaign_configs),
                run_score=state.run_score,
                best_run_score=state.best_run_score,
                message=f"Level {finished_level}/{len(campaign_configs)} abgeschlossen. "
                f"Starte Level {next_level}/{len(campaign_configs)}.",
            ),
            current_level_index + 1,
        )
    return state, current_level_index


def run_cli(
    input_stream: Iterable[str] | None = None,
    config: GameConfig | None = None,
    campaign_configs: Iterable[GameConfig] | None = None,
    save_file: str | Path | None = None,
) -> int:
    campaign = tuple(campaign_configs) if campaign_configs is not None else tuple()
    if not campaign:
        if config is not None:
            campaign = (config,)
        else:
            campaign = build_campaign_configs()

    persisted_best_run, load_warning = load_best_run_score(save_file=save_file)
    current_level_index = 0
    state = GameState(
        config=campaign[current_level_index],
        campaign_level_index=1,
        campaign_level_total=len(campaign),
        best_run_score=persisted_best_run,
    )
    if SCORE_BALANCE_LOAD_WARNING:
        state.last_message = merge_events(state.last_message, format_event("CONFIG", SCORE_BALANCE_LOAD_WARNING))
    if load_warning:
        state.last_message = merge_events(state.last_message, format_event("SAVE", load_warning))
    print("=== Vertical Slice (No-Dependency CLI) ===")
    print(
        f"Kampagne: Level {state.campaign_level_index}/{state.campaign_level_total} | "
        f"Layout: {state.config.layout_name} | Hazard-Dichte: {state.config.hazard_density}"
    )
    print("Befehle: W/A/S/D bewegen, R startet neu, Q beendet.")
    print("Nach Missionsende: R fuer Neustart, Enter beendet.")

    if input_stream is None:
        def read_command() -> str | None:
            try:
                return input("> ")
            except EOFError:
                return None

        while True:
            state, current_level_index = _advance_campaign_level(state, campaign, current_level_index)
            print()
            print(render(state))
            if state.status == "running":
                cmd = read_command()
                if cmd is None:
                    break
                if is_restart_command(cmd):
                    state = restart_game(
                        config=campaign[0],
                        campaign_level_index=1,
                        campaign_level_total=len(campaign),
                        run_score=0,
                        best_run_score=state.best_run_score,
                        message="Kampagne neu gestartet. Level 1 aktiv.",
                    )
                    current_level_index = 0
                    continue
                process_input(state, cmd)
                continue

            cmd = read_command()
            if cmd is None:
                break
            if is_restart_command(cmd):
                state = restart_game(
                    config=campaign[0],
                    campaign_level_index=1,
                    campaign_level_total=len(campaign),
                    run_score=0,
                    best_run_score=state.best_run_score,
                    message="Kampagne neu gestartet. Level 1 aktiv.",
                )
                current_level_index = 0
                continue
            break
    else:
        for cmd in input_stream:
            state, current_level_index = _advance_campaign_level(state, campaign, current_level_index)
            if is_restart_command(cmd):
                state = restart_game(
                    config=campaign[0],
                    campaign_level_index=1,
                    campaign_level_total=len(campaign),
                    run_score=0,
                    best_run_score=state.best_run_score,
                    message="Kampagne neu gestartet. Level 1 aktiv.",
                )
                current_level_index = 0
                continue
            if state.status == "running":
                process_input(state, cmd)
                continue
            break

    state, current_level_index = _advance_campaign_level(state, campaign, current_level_index)

    new_record = False
    if state.status in {"win", "lose"} and state.run_score > state.best_run_score:
        state.best_run_score = state.run_score
        new_record = True

    save_warning = save_best_run_score(state.best_run_score, save_file=save_file)
    if save_warning:
        state.last_message = merge_events(state.last_message, format_event("SAVE", save_warning))

    print()
    print(render(state))
    result = "WIN" if state.status == "win" else "LOSE" if state.status == "lose" else "OFFEN"
    print("ERGEBNIS:", result)
    print(f"SCORE: {state.run_score}")
    print(f"BEST-RUN: {state.best_run_score}")
    if new_record:
        print("NEUER BEST-RUN!")
    return 0 if state.status == "win" else 1


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vertical Slice CLI")
    campaign_layouts = [level.layout_name for level in CAMPAIGN_LEVELS]
    parser.add_argument(
        "--layout",
        choices=campaign_layouts,
        default=campaign_layouts[0],
        help="Waehlt das Start-Layout der Kampagne.",
    )
    parser.add_argument(
        "--hazard-density",
        choices=list(HAZARD_DENSITY_FACTORS),
        default="normal",
        help="Globaler Override fuer die Level-Kurve (normal = Kurven-Defaults pro Level).",
    )
    parser.add_argument(
        "--list-layouts",
        action="store_true",
        help="Zeigt verfuegbare Layouts und beendet das Programm.",
    )
    parser.add_argument(
        "--save-file",
        default=str(resolve_save_file_path()),
        help="Pfad zur lokalen Meta-Progression-Datei (Best-Run als JSON).",
    )
    parser.add_argument(
        "--menu",
        choices=("auto", "on", "off"),
        default="auto",
        help="Steuert das Start-Menue (auto = nur in interaktiven Terminals).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def print_layouts() -> None:
    print("Verfuegbare Layouts:")
    for name, description in list_available_layouts().items():
        print(f"- {name}: {description}")


def should_launch_start_menu(
    menu_mode: str,
    stdin: object | None = None,
    stdout: object | None = None,
) -> bool:
    if menu_mode == "on":
        return True
    if menu_mode == "off":
        return False

    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout

    stdin_is_tty = bool(getattr(in_stream, "isatty", lambda: False)())
    stdout_is_tty = bool(getattr(out_stream, "isatty", lambda: False)())
    return stdin_is_tty and stdout_is_tty


def run_test_suite_from_menu(
    output_func: Callable[[str], None] | None = None,
) -> int:
    write_output = print if output_func is None else output_func
    package_dir = Path(__file__).resolve().parent.parent
    test_script = package_dir / "run_tests.sh"

    write_output("")
    write_output("=== Tests ===")
    if not test_script.is_file():
        write_output(f"Test-Skript nicht gefunden: {test_script}")
        return 127

    write_output(f"Starte Testsuite: {test_script}")
    result = subprocess.run(
        ["bash", str(test_script)],
        cwd=package_dir,
        check=False,
    )
    return result.returncode


def run_start_menu(
    default_layout: str = "classic",
    default_hazard_density: str = "normal",
    input_func: Callable[[str], str] | None = None,
    output_func: Callable[[str], None] | None = None,
    run_tests_func: Callable[[], int] | None = None,
) -> StartMenuSelection | None:
    read_input = input if input_func is None else input_func
    write_output = print if output_func is None else output_func
    available_layouts = list_available_layouts()
    campaign_layout_order = [level.layout_name for level in CAMPAIGN_LEVELS]
    hazard_options = list(HAZARD_DENSITY_FACTORS)

    selected_layout = default_layout if default_layout in available_layouts else campaign_layout_order[0]
    selected_density = normalize_hazard_density(default_hazard_density)

    while True:
        write_output("")
        write_output("=== Start-Menue ===")
        write_output(f"1) Layout waehlen (aktuell: {selected_layout})")
        write_output(f"2) Hazard-Dichte waehlen (aktuell: {selected_density})")
        write_output("3) Kampagnenmodus starten")
        write_output("4) Tests ausfuehren")
        write_output("5) Info anzeigen")
        write_output("Q) Beenden")

        try:
            choice = read_input("Auswahl: ").strip().lower()
        except EOFError:
            return None

        if choice in QUIT_COMMANDS:
            return None

        if choice == "1":
            write_output("")
            write_output("Layouts:")
            for index, layout_name in enumerate(campaign_layout_order, start=1):
                description = available_layouts.get(layout_name, "")
                write_output(f"{index}) {layout_name}: {description}")
            write_output("Enter behaelt das aktuelle Layout.")
            try:
                layout_choice = read_input("Layout: ").strip().lower()
            except EOFError:
                return None
            if not layout_choice:
                continue
            if layout_choice.isdigit():
                selected_index = int(layout_choice) - 1
                if 0 <= selected_index < len(campaign_layout_order):
                    selected_layout = campaign_layout_order[selected_index]
                else:
                    write_output("Ungueltige Layout-Nummer.")
                continue
            if layout_choice in available_layouts:
                selected_layout = layout_choice
            else:
                write_output("Ungueltiges Layout.")
            continue

        if choice == "2":
            write_output("")
            write_output("Hazard-Dichte:")
            for index, density in enumerate(hazard_options, start=1):
                write_output(f"{index}) {density}")
            write_output("Enter behaelt die aktuelle Dichte.")
            try:
                density_choice = read_input("Dichte: ").strip().lower()
            except EOFError:
                return None
            if not density_choice:
                continue
            if density_choice.isdigit():
                selected_index = int(density_choice) - 1
                if 0 <= selected_index < len(hazard_options):
                    selected_density = hazard_options[selected_index]
                else:
                    write_output("Ungueltige Dichte-Nummer.")
                continue
            try:
                selected_density = normalize_hazard_density(density_choice)
            except ValueError:
                write_output("Ungueltige Hazard-Dichte.")
            continue

        if choice == "4":
            exit_code = (
                run_test_suite_from_menu(output_func=write_output)
                if run_tests_func is None
                else run_tests_func()
            )
            if exit_code == 0:
                write_output("Tests erfolgreich abgeschlossen.")
            else:
                write_output(f"Tests mit Exit-Code {exit_code} beendet.")
            write_output("Zurueck im Start-Menue.")
            continue

        if choice == "5":
            write_output("")
            write_output("=== Info ===")
            write_output(f"Start-Layout : {selected_layout}")
            write_output(f"Hazard-Dichte: {selected_density}")
            write_output("Kampagnenstart: Option 3 im Menue.")
            write_output("Tests ausfuehren: Option 4 im Menue oder ./run_tests.sh")
            write_output("Layout-Liste via CLI: --list-layouts")
            continue

        if choice == "3":
            return StartMenuSelection(layout_name=selected_layout, hazard_density=selected_density)

        write_output("Ungueltige Auswahl. Bitte 1, 2, 3, 4, 5 oder Q eingeben.")


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    if args.list_layouts:
        print_layouts()
        raise SystemExit(0)

    selected_layout = args.layout
    selected_hazard_density = args.hazard_density
    if should_launch_start_menu(args.menu):
        menu_selection = run_start_menu(
            default_layout=selected_layout,
            default_hazard_density=selected_hazard_density,
        )
        if menu_selection is None:
            print("Start abgebrochen.")
            raise SystemExit(1)
        selected_layout = menu_selection.layout_name
        selected_hazard_density = menu_selection.hazard_density

    campaign = build_campaign_configs(layout_name=selected_layout, hazard_density=selected_hazard_density)
    raise SystemExit(run_cli(campaign_configs=campaign, save_file=args.save_file))


if __name__ == "__main__":
    main()
