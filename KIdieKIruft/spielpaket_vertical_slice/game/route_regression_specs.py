"""Shared deterministic route specs for regression checks."""

from __future__ import annotations

from dataclasses import dataclass

Position = tuple[int, int]


@dataclass(frozen=True)
class RouteRegressionSpec:
    profile_id: str
    commands: str
    expected_status: str
    hp: int
    turns_left: int
    player_pos: Position
    enemy_pos: Position
    score_range: tuple[int, int]


ROUTE_REGRESSION_SPECS: dict[str, tuple[RouteRegressionSpec, ...]] = {
    "classic": (
        RouteRegressionSpec(
            profile_id="extract_fast_v1",
            commands="wdsdddaasssdd",
            expected_status="win",
            hp=2,
            turns_left=3,
            player_pos=(4, 4),
            enemy_pos=(4, 3),
            score_range=(920, 1040),
        ),
        RouteRegressionSpec(
            profile_id="early_collapse_v1",
            commands="wwwwww",
            expected_status="lose",
            hp=0,
            turns_left=10,
            player_pos=(0, 0),
            enemy_pos=(0, 0),
            score_range=(0, 40),
        ),
    ),
    "corridor": (
        RouteRegressionSpec(
            profile_id="corridor_dash_v1",
            commands="dwwddwdwd",
            expected_status="win",
            hp=2,
            turns_left=5,
            player_pos=(5, 0),
            enemy_pos=(5, 0),
            score_range=(730, 830),
        ),
        RouteRegressionSpec(
            profile_id="corridor_pinch_v1",
            commands="wddwsad",
            expected_status="lose",
            hp=0,
            turns_left=7,
            player_pos=(2, 3),
            enemy_pos=(2, 3),
            score_range=(0, 40),
        ),
    ),
    "crossfire": (
        RouteRegressionSpec(
            profile_id="crossfire_thread_v1",
            commands="wwaaddddwaaww",
            expected_status="win",
            hp=1,
            turns_left=0,
            player_pos=(2, 0),
            enemy_pos=(2, 0),
            score_range=(540, 640),
        ),
        RouteRegressionSpec(
            profile_id="crossfire_crash_v1",
            commands="dwwwwwsws",
            expected_status="lose",
            hp=0,
            turns_left=4,
            player_pos=(3, 1),
            enemy_pos=(3, 1),
            score_range=(0, 40),
        ),
    ),
}


def iter_route_regression_specs(layout_name: str) -> tuple[RouteRegressionSpec, ...]:
    try:
        return ROUTE_REGRESSION_SPECS[layout_name]
    except KeyError as exc:
        raise KeyError(f"Unbekanntes Layout fuer Route-Regression: {layout_name}") from exc


def get_route_regression_spec(layout_name: str, profile_id: str) -> RouteRegressionSpec:
    for spec in iter_route_regression_specs(layout_name):
        if spec.profile_id == profile_id:
            return spec
    raise KeyError(f"Kein Route-Profil '{profile_id}' fuer Layout '{layout_name}' gefunden.")


def get_route_regression_spec_for_outcome(layout_name: str, expected_status: str) -> RouteRegressionSpec:
    matches = [spec for spec in iter_route_regression_specs(layout_name) if spec.expected_status == expected_status]
    if not matches:
        raise KeyError(f"Kein Route-Profil fuer Layout '{layout_name}' mit Outcome '{expected_status}'.")
    if len(matches) > 1:
        profile_ids = ", ".join(spec.profile_id for spec in matches)
        raise ValueError(
            f"Mehrere Route-Profile fuer Layout '{layout_name}' mit Outcome '{expected_status}': {profile_ids}"
        )
    return matches[0]
