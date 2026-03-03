import unittest
from collections import deque
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from game.route_regression_specs import (
    get_route_regression_spec,
    get_route_regression_spec_for_outcome,
)
from game.vertical_slice import (
    CAMPAIGN_LEVELS,
    DEFAULT_SCORE_BALANCE_PROFILES,
    MOVE_MAP,
    GameState,
    build_extraction_route_zone,
    build_campaign_configs,
    build_game_config,
    choose_enemy_step,
    distance_to_zone,
    enemy_step_score_fields,
    list_available_layouts,
    load_score_balance_profiles,
    load_score_balance_profiles_with_fallback,
    manhattan_distance,
    main,
    process_input,
    render,
    resolve_score_balance_profiles_path,
    run_cli,
    run_start_menu,
    should_launch_start_menu,
)


class VerticalSliceTests(unittest.TestCase):
    def _layout_names(self) -> tuple[str, ...]:
        return tuple(sorted(list_available_layouts()))

    def _snapshot_state(self, state: GameState) -> str:
        return (
            f"status={state.status}, hp={state.hp}, turns_left={state.turns_left}, "
            f"player={state.player_pos}, enemy={state.enemy_pos}, "
            f"score={state.run_score}, best={state.best_run_score}, "
            f"cells={len(state.collected_cells)}/{len(state.config.energy_cells)}, "
            f"extraction_active={state.extraction_active}, last_message={state.last_message!r}"
        )

    def _assert_scripted_route(self, layout_name: str, profile_id: str) -> GameState:
        route_spec = get_route_regression_spec(layout_name, profile_id)
        commands = tuple(route_spec.commands)
        level = next((item for item in CAMPAIGN_LEVELS if item.layout_name == layout_name), None)
        if level is None:
            config = build_game_config(layout_name=layout_name, hazard_density="normal")
        else:
            config = build_game_config(
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
        state = GameState(config=config)
        enemy_event_seen = False
        route_text = "".join(commands)

        for step_index, cmd in enumerate(commands, start=1):
            if state.status != "running":
                self.fail(
                    f"Route-Regression in {layout_name}/{profile_id}: Mission endete vor Schritt {step_index}. "
                    f"Route='{route_text}'. {self._snapshot_state(state)}"
                )

            process_input(state, cmd)

            if "[GEGNER]" in state.last_message:
                enemy_event_seen = True

            if step_index < len(commands) and state.status != "running":
                self.fail(
                    f"Route-Regression in {layout_name}/{profile_id}: Mission endete zu frueh in Schritt {step_index} "
                    f"mit Eingabe '{cmd}'. Route='{route_text}'. {self._snapshot_state(state)}"
                )

        self.assertTrue(
            enemy_event_seen,
            msg=f"Route-Regression in {layout_name}/{profile_id}: Gegner war in Route '{route_text}' nicht aktiv.",
        )
        self.assertEqual(
            state.status,
            route_spec.expected_status,
            msg=(
                f"Route-Regression in {layout_name}/{profile_id}: Unerwarteter Endstatus nach Route '{route_text}'. "
                f"{self._snapshot_state(state)}"
            ),
        )
        self.assertEqual(
            state.hp,
            route_spec.hp,
            msg=f"Route-Regression in {layout_name}/{profile_id}: HP-Abweichung fuer Route '{route_text}'.",
        )
        self.assertEqual(
            state.turns_left,
            route_spec.turns_left,
            msg=f"Route-Regression in {layout_name}/{profile_id}: Turn-Limit-Abweichung fuer Route '{route_text}'.",
        )
        self.assertEqual(
            state.player_pos,
            route_spec.player_pos,
            msg=f"Route-Regression in {layout_name}/{profile_id}: Spielerposition weicht ab fuer Route '{route_text}'.",
        )
        self.assertEqual(
            state.enemy_pos,
            route_spec.enemy_pos,
            msg=f"Route-Regression in {layout_name}/{profile_id}: Gegnerposition weicht ab fuer Route '{route_text}'.",
        )
        return state

    def _clone_state(self, state: GameState) -> GameState:
        clone = GameState(
            config=state.config,
            campaign_level_index=state.campaign_level_index,
            campaign_level_total=state.campaign_level_total,
        )
        clone.player_pos = state.player_pos
        clone.enemy_pos = state.enemy_pos
        clone.hp = state.hp
        clone.turns_left = state.turns_left
        clone.collected_cells = set(state.collected_cells)
        clone.extraction_active = state.extraction_active
        clone.status = state.status
        clone.last_message = state.last_message
        clone.run_score = state.run_score
        clone.best_run_score = state.best_run_score
        return clone

    def _assert_score_range_for_outcome(self, layout_name: str, expected_status: str) -> None:
        route_spec = get_route_regression_spec_for_outcome(layout_name, expected_status)
        state = self._assert_scripted_route(layout_name, route_spec.profile_id)
        score_min, score_max = route_spec.score_range
        self.assertGreaterEqual(
            state.run_score,
            score_min,
            msg=(
                f"Score-Regression in {layout_name}/{route_spec.profile_id}: Score {state.run_score} liegt unter Minimum "
                f"{score_min}. {self._snapshot_state(state)}"
            ),
        )
        self.assertLessEqual(
            state.run_score,
            score_max,
            msg=(
                f"Score-Regression in {layout_name}/{route_spec.profile_id}: Score {state.run_score} liegt ueber Maximum "
                f"{score_max}. {self._snapshot_state(state)}"
            ),
        )

    def _state_key(self, state: GameState) -> tuple:
        return (
            state.player_pos,
            state.enemy_pos,
            state.hp,
            state.turns_left,
            frozenset(state.collected_cells),
            state.extraction_active,
            state.status,
        )

    def _find_route_for_goal(self, config, require_extraction: bool) -> tuple[str, ...]:
        start = GameState(config=config)
        queue = deque([(start, tuple())])
        visited = {self._state_key(start)}

        while queue:
            state, route = queue.popleft()
            if require_extraction and state.status == "win":
                return route
            if not require_extraction and len(state.collected_cells) == len(config.energy_cells):
                return route

            if state.status != "running":
                continue

            for cmd in MOVE_MAP:
                next_state = self._clone_state(state)
                process_input(next_state, cmd)
                key = self._state_key(next_state)
                if key in visited:
                    continue
                visited.add(key)
                queue.append((next_state, route + (cmd,)))

        self.fail(f"Kein gueltiger Pfad fuer Layout {config.layout_name} gefunden.")

    def _build_collection_route(self, config) -> tuple[str, ...]:
        self.assertEqual(
            len(config.energy_cells),
            3,
            msg=f"Layout {config.layout_name} muss genau 3 Energiezellen haben.",
        )
        return self._find_route_for_goal(config, require_extraction=False)

    def _build_win_route(self, config) -> tuple[str, ...]:
        return self._find_route_for_goal(config, require_extraction=True)

    def _get_out_of_bounds_command(self, config) -> str:
        x, y = config.start_pos
        if y == 0:
            return "w"
        if y == config.height - 1:
            return "s"
        if x == 0:
            return "a"
        if x == config.width - 1:
            return "d"
        self.fail(f"Startposition fuer Layout {config.layout_name} liegt nicht am Rand.")

    def _build_menu_input(self, entries: list[str]):
        values = iter(entries)

        def _reader(_prompt: str) -> str:
            try:
                return next(values)
            except StopIteration as exc:
                raise EOFError from exc

        return _reader

    def _build_score_balance_payload(self) -> dict[str, object]:
        return {
            "version": 1,
            "profiles": {
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
            },
        }

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(f"{json.dumps(payload, ensure_ascii=True, indent=2)}\n", encoding="utf-8")

    def test_at_least_two_alternative_layouts_are_available(self) -> None:
        layouts = list_available_layouts()
        self.assertIn("classic", layouts)
        self.assertGreaterEqual(len(layouts) - 1, 2)

    def test_000_scripted_win_routes_remain_reproducible_with_active_enemy(self) -> None:
        for layout_name in self._layout_names():
            route_spec = get_route_regression_spec_for_outcome(layout_name, "win")
            state = self._assert_scripted_route(layout_name, route_spec.profile_id)
            if route_spec.expected_status != "win":
                self.assertIn(
                    "[MISSION] Du bist ausgeschaltet.",
                    state.last_message,
                    msg=(
                        "Route-Regression in "
                        f"{layout_name}/{route_spec.profile_id}: erwarteter Lose-Abschluss fehlt."
                    ),
                )
                continue
            self.assertTrue(
                state.extraction_active,
                msg=f"Route-Regression in {layout_name}/{route_spec.profile_id}: Extraktion blieb inaktiv.",
            )
            self.assertEqual(
                state.player_pos,
                state.config.extraction_pos,
                msg=(
                    "Route-Regression in "
                    f"{layout_name}/{route_spec.profile_id}: Spieler steht nicht auf Extraktion."
                ),
            )
            self.assertIn(
                "[MISSION] Extraktion erfolgreich.",
                state.last_message,
                msg=f"Route-Regression in {layout_name}/{route_spec.profile_id}: Win-Event fehlt im Abschluss-Log.",
            )

    def test_001_scripted_lose_routes_remain_reproducible_with_active_enemy(self) -> None:
        for layout_name in self._layout_names():
            route_spec = get_route_regression_spec_for_outcome(layout_name, "lose")
            state = self._assert_scripted_route(layout_name, route_spec.profile_id)
            if route_spec.expected_status != "lose":
                self.assertIn(
                    "[MISSION] Extraktion erfolgreich.",
                    state.last_message,
                    msg=(
                        "Route-Regression in "
                        f"{layout_name}/{route_spec.profile_id}: erwarteter Win-Abschluss fehlt."
                    ),
                )
                continue
            self.assertIn(
                "[GEGNER] Kollision!",
                state.last_message,
                msg=(
                    "Route-Regression in "
                    f"{layout_name}/{route_spec.profile_id}: Gegner-Kollision fehlt im Abschluss-Log."
                ),
            )
            self.assertIn(
                "[MISSION] Du bist ausgeschaltet.",
                state.last_message,
                msg=(
                    "Route-Regression in "
                    f"{layout_name}/{route_spec.profile_id}: Lose-Ursache ist nicht gegnerbedingt."
                ),
            )

    def test_002_classic_score_ranges_for_win_and_lose_routes(self) -> None:
        self._assert_score_range_for_outcome("classic", "win")
        self._assert_score_range_for_outcome("classic", "lose")

    def test_003_corridor_score_ranges_for_win_and_lose_routes(self) -> None:
        self._assert_score_range_for_outcome("corridor", "win")
        self._assert_score_range_for_outcome("corridor", "lose")

    def test_004_crossfire_score_ranges_for_win_and_lose_routes(self) -> None:
        self._assert_score_range_for_outcome("crossfire", "win")
        self._assert_score_range_for_outcome("crossfire", "lose")

    def test_hazard_density_changes_active_hazard_count(self) -> None:
        low = build_game_config(layout_name="classic", hazard_density="low")
        normal = build_game_config(layout_name="classic", hazard_density="normal")
        high = build_game_config(layout_name="classic", hazard_density="high")
        self.assertLess(len(low.hazard_tiles), len(normal.hazard_tiles))
        self.assertLess(len(normal.hazard_tiles), len(high.hazard_tiles))

    def test_campaign_levels_are_centrally_defined(self) -> None:
        self.assertGreaterEqual(len(CAMPAIGN_LEVELS), 3)
        available_layouts = list_available_layouts()
        for level in CAMPAIGN_LEVELS:
            self.assertIn(level.layout_name, available_layouts)
            self.assertGreater(level.starting_hp, 0)
            self.assertGreater(level.turn_limit, 0)
            self.assertGreaterEqual(level.hazard_count, 0)
            self.assertGreater(level.enemy_turns_per_round, 0)
            self.assertGreaterEqual(level.enemy_route_cutoff_weight, 0)
            self.assertGreaterEqual(level.enemy_chase_weight, 0)
            self.assertGreater(
                level.enemy_route_cutoff_weight + level.enemy_chase_weight,
                0,
                msg=f"Level {level.level_id} braucht mindestens ein aktives Heuristik-Gewicht.",
            )
            self.assertGreater(level.score_balance.turn_reward, 0)
            self.assertGreater(level.score_balance.energy_cell_reward, 0)
            self.assertGreater(level.score_balance.extraction_activation_reward, 0)
            self.assertGreater(level.score_balance.level_win_base_reward, 0)
            self.assertGreaterEqual(level.score_balance.hazard_damage_penalty, 0)
            self.assertGreaterEqual(level.score_balance.enemy_collision_penalty, 0)

    def test_score_balance_profiles_load_from_external_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "score_balance_profiles.json"
            payload = self._build_score_balance_payload()
            payload["profiles"]["L2"]["turn_reward"] = 11
            self._write_json(config_file, payload)

            loaded = load_score_balance_profiles(score_balance_file=config_file)

        self.assertEqual(loaded["L2"].turn_reward, 11)
        self.assertEqual(loaded["L3"].enemy_collision_penalty, 52)
        self.assertEqual(sorted(loaded), ["L1", "L2", "L3"])

    def test_score_balance_profiles_validate_missing_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "score_balance_profiles.json"
            payload = self._build_score_balance_payload()
            del payload["profiles"]["L3"]["enemy_collision_penalty"]
            self._write_json(config_file, payload)

            with self.assertRaises(ValueError) as err_ctx:
                load_score_balance_profiles(score_balance_file=config_file)

        error_text = str(err_ctx.exception)
        self.assertIn("Pflichtfeld fehlt", error_text)
        self.assertIn("L3", error_text)
        self.assertIn("enemy_collision_penalty", error_text)

    def test_score_balance_profiles_fallback_on_invalid_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "score_balance_profiles.json"
            payload = self._build_score_balance_payload()
            payload["profiles"]["L1"]["turn_reward"] = -5
            self._write_json(config_file, payload)

            loaded, warning = load_score_balance_profiles_with_fallback(
                score_balance_file=config_file,
                fallback_profiles=DEFAULT_SCORE_BALANCE_PROFILES,
            )

        self.assertEqual(loaded, DEFAULT_SCORE_BALANCE_PROFILES)
        self.assertIsNotNone(warning)
        self.assertIn("L1.turn_reward", warning)
        self.assertIn("Fallback-Profilwerte", warning)

    def test_default_score_balance_profile_path_exists(self) -> None:
        path = resolve_score_balance_profiles_path()
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "score_balance_profiles.json")

    def test_start_menu_allows_layout_and_density_selection(self) -> None:
        output_lines: list[str] = []
        menu_selection = run_start_menu(
            default_layout="classic",
            default_hazard_density="normal",
            input_func=self._build_menu_input(["1", "2", "2", "3", "3"]),
            output_func=output_lines.append,
        )
        self.assertIsNotNone(menu_selection)
        self.assertEqual(menu_selection.layout_name, "corridor")
        self.assertEqual(menu_selection.hazard_density, "high")

    def test_start_menu_info_shows_test_hint(self) -> None:
        output_lines: list[str] = []
        menu_selection = run_start_menu(
            default_layout="classic",
            default_hazard_density="normal",
            input_func=self._build_menu_input(["5", "3"]),
            output_func=output_lines.append,
        )
        self.assertIsNotNone(menu_selection)
        joined = "\n".join(output_lines)
        self.assertIn("Tests ausfuehren: Option 4 im Menue oder ./run_tests.sh", joined)

    def test_start_menu_runs_tests_and_returns_to_menu(self) -> None:
        output_lines: list[str] = []
        run_tests_calls: list[str] = []

        def _run_tests() -> int:
            run_tests_calls.append("called")
            return 0

        menu_selection = run_start_menu(
            default_layout="classic",
            default_hazard_density="normal",
            input_func=self._build_menu_input(["4", "3"]),
            output_func=output_lines.append,
            run_tests_func=_run_tests,
        )
        self.assertIsNotNone(menu_selection)
        self.assertEqual(len(run_tests_calls), 1)
        joined = "\n".join(output_lines)
        self.assertIn("4) Tests ausfuehren", joined)
        self.assertIn("Tests erfolgreich abgeschlossen.", joined)

    def test_start_menu_quit_aborts_start(self) -> None:
        menu_selection = run_start_menu(
            input_func=self._build_menu_input(["q"]),
            output_func=lambda _line: None,
        )
        self.assertIsNone(menu_selection)

    def test_start_menu_auto_mode_depends_on_tty(self) -> None:
        class _FakeStream:
            def __init__(self, is_tty: bool) -> None:
                self._is_tty = is_tty

            def isatty(self) -> bool:
                return self._is_tty

        self.assertTrue(should_launch_start_menu("auto", stdin=_FakeStream(True), stdout=_FakeStream(True)))
        self.assertFalse(should_launch_start_menu("auto", stdin=_FakeStream(True), stdout=_FakeStream(False)))
        self.assertTrue(should_launch_start_menu("on", stdin=_FakeStream(False), stdout=_FakeStream(False)))
        self.assertFalse(should_launch_start_menu("off", stdin=_FakeStream(True), stdout=_FakeStream(True)))

    def test_main_e2e_start_menu_stream_applies_layout_and_density(self) -> None:
        menu_stream = ["1", "2", "2", "3", "3"]
        with TemporaryDirectory() as temp_dir:
            save_file = Path(temp_dir) / "meta_progression.json"
            with patch("game.vertical_slice.input", side_effect=menu_stream), patch(
                "game.vertical_slice.run_cli",
                return_value=0,
            ) as run_cli_mock:
                with self.assertRaises(SystemExit) as exit_ctx:
                    main(["--menu", "on", "--save-file", str(save_file)])

        self.assertEqual(exit_ctx.exception.code, 0)
        run_cli_mock.assert_called_once()
        called_kwargs = run_cli_mock.call_args.kwargs
        campaign = called_kwargs["campaign_configs"]
        self.assertEqual(campaign[0].layout_name, "corridor")
        self.assertTrue(all(level.hazard_density == "high" for level in campaign))
        self.assertEqual(Path(called_kwargs["save_file"]), save_file)

    def test_main_e2e_start_menu_allows_test_run_before_campaign_start(self) -> None:
        menu_stream = ["4", "3"]
        with TemporaryDirectory() as temp_dir:
            save_file = Path(temp_dir) / "meta_progression.json"
            with patch("game.vertical_slice.input", side_effect=menu_stream), patch(
                "game.vertical_slice.run_test_suite_from_menu",
                return_value=0,
            ) as run_tests_mock, patch(
                "game.vertical_slice.run_cli",
                return_value=0,
            ) as run_cli_mock:
                with self.assertRaises(SystemExit) as exit_ctx:
                    main(["--menu", "on", "--save-file", str(save_file)])

        self.assertEqual(exit_ctx.exception.code, 0)
        run_tests_mock.assert_called_once()
        run_cli_mock.assert_called_once()

    def test_later_campaign_levels_use_multiple_enemy_turns(self) -> None:
        self.assertTrue(
            any(level.enemy_turns_per_round > 1 for level in CAMPAIGN_LEVELS[1:]),
            msg="Mindestens ein spaeteres Kampagnenlevel muss enemy_turns_per_round > 1 nutzen.",
        )

    def test_enemy_intensity_is_configurable_in_game_config(self) -> None:
        low = build_game_config(layout_name="classic", hazard_density="normal", enemy_turns_per_round=1)
        high = build_game_config(layout_name="classic", hazard_density="normal", enemy_turns_per_round=2)
        self.assertEqual(low.enemy_turns_per_round, 1)
        self.assertEqual(high.enemy_turns_per_round, 2)

    def test_campaign_difficulty_increases_per_level(self) -> None:
        campaign = build_campaign_configs(layout_name="classic", hazard_density="normal")
        self.assertEqual(len(campaign), len(CAMPAIGN_LEVELS))

        for previous, current in zip(campaign, campaign[1:]):
            previous_hazards = len(previous.hazard_tiles)
            current_hazards = len(current.hazard_tiles)
            self.assertGreaterEqual(current_hazards, previous_hazards)
            self.assertLessEqual(current.turn_limit, previous.turn_limit)
            self.assertGreaterEqual(current.enemy_turns_per_round, previous.enemy_turns_per_round)
            self.assertTrue(
                current_hazards > previous_hazards
                or current.turn_limit < previous.turn_limit
                or current.enemy_turns_per_round > previous.enemy_turns_per_round,
                msg="Jedes spaetere Level muss bedrohlicher sein als das vorherige.",
            )

    def test_classic_remains_winnable_with_bfs_route(self) -> None:
        config = build_game_config(layout_name="classic", hazard_density="normal")
        route = self._build_win_route(config)
        self.assertGreater(len(route), 0)

        state = GameState(config=config)
        for cmd in route:
            process_input(state, cmd)
            if state.status != "running":
                break
        self.assertEqual(state.status, "win")

    def test_campaign_l1_remains_winnable_with_deterministic_bfs_route(self) -> None:
        l1_config = build_campaign_configs(layout_name="classic", hazard_density="normal")[0]
        self.assertEqual(l1_config.layout_name, "classic")

        route = self._build_win_route(l1_config)
        self.assertGreater(len(route), 0)
        self.assertEqual("".join(route), "wdsdddaasssdd")

        state = GameState(config=l1_config)
        for cmd in route:
            process_input(state, cmd)
            if state.status != "running":
                break
        self.assertEqual(state.status, "win")

    def test_custom_layout_applies_config(self) -> None:
        config = build_game_config(layout_name="corridor", hazard_density="normal")
        state = GameState(config=config)
        self.assertEqual(state.config.width, 6)
        self.assertEqual(state.config.height, 5)
        self.assertEqual(state.player_pos, (0, 4))
        self.assertEqual(state.enemy_pos, (5, 4))

    def test_move_changes_position(self) -> None:
        state = GameState()
        process_input(state, "d")
        self.assertEqual(state.player_pos, (1, 0))

    def test_enemy_moves_deterministically_after_each_turn(self) -> None:
        state = GameState(config=build_game_config(layout_name="classic", hazard_density="normal"))
        process_input(state, "d")
        self.assertEqual(state.enemy_pos, (3, 0))
        process_input(state, "s")
        self.assertEqual(state.enemy_pos, (2, 0))
        self.assertIn("[GEGNER]", state.last_message)

    def test_enemy_prioritizes_route_cutoff_when_extraction_is_active(self) -> None:
        state = GameState(
            config=build_game_config(
                layout_name="corridor",
                hazard_density="normal",
                enemy_route_cutoff_weight=2,
                enemy_chase_weight=1,
            )
        )
        state.extraction_active = True
        state.collected_cells = set(state.config.energy_cells)
        state.player_pos = (2, 0)
        state.enemy_pos = (5, 4)

        next_step = choose_enemy_step(state)
        self.assertEqual(next_step, (5, 3))

    def test_later_level_weights_create_more_aggressive_route_cutoff(self) -> None:
        low_pressure = build_game_config(
            layout_name="corridor",
            hazard_density="normal",
            enemy_route_cutoff_weight=CAMPAIGN_LEVELS[0].enemy_route_cutoff_weight,
            enemy_chase_weight=CAMPAIGN_LEVELS[0].enemy_chase_weight,
        )
        high_pressure = build_game_config(
            layout_name="corridor",
            hazard_density="normal",
            enemy_route_cutoff_weight=CAMPAIGN_LEVELS[1].enemy_route_cutoff_weight,
            enemy_chase_weight=CAMPAIGN_LEVELS[1].enemy_chase_weight,
        )

        low_state = GameState(config=low_pressure)
        high_state = GameState(config=high_pressure)
        for state in (low_state, high_state):
            state.extraction_active = True
            state.collected_cells = set(state.config.energy_cells)
            state.player_pos = (0, 4)
            state.enemy_pos = (4, 2)

        low_step = choose_enemy_step(low_state)
        high_step = choose_enemy_step(high_state)
        self.assertEqual(low_step, (3, 2))
        self.assertEqual(high_step, (5, 2))

        route_zone = build_extraction_route_zone(high_state)
        self.assertGreater(distance_to_zone(low_step, route_zone), distance_to_zone(high_step, route_zone))
        self.assertGreater(manhattan_distance(high_step, high_state.player_pos), manhattan_distance(low_step, low_state.player_pos))

    def test_enemy_step_score_fields_document_tiebreak_order(self) -> None:
        chase_state = GameState(
            config=build_game_config(
                layout_name="classic",
                hazard_density="normal",
                enemy_route_cutoff_weight=0,
                enemy_chase_weight=1,
            )
        )
        self.assertEqual(
            enemy_step_score_fields(chase_state),
            ("collision_priority", "weighted_pressure", "chase_distance", "index"),
        )

        route_state = GameState(
            config=build_game_config(
                layout_name="corridor",
                hazard_density="normal",
                enemy_route_cutoff_weight=2,
                enemy_chase_weight=1,
            )
        )
        route_state.player_pos = (0, 0)
        route_state.enemy_pos = (1, 0)
        self.assertEqual(
            enemy_step_score_fields(route_state),
            (
                "collision_priority",
                "weighted_pressure",
                "route_distance",
                "key_distance",
                "chase_distance",
                "extraction_distance",
                "index",
            ),
        )

        route_state.enemy_pos = route_state.player_pos
        self.assertEqual(
            enemy_step_score_fields(route_state),
            (
                "weighted_pressure",
                "route_distance",
                "key_distance",
                "chase_distance",
                "extraction_distance",
                "collision_priority",
                "index",
            ),
        )

    def test_weighted_profiles_soften_collision_priority_after_overlap(self) -> None:
        state = GameState(
            config=build_game_config(
                layout_name="corridor",
                hazard_density="normal",
                enemy_route_cutoff_weight=2,
                enemy_chase_weight=1,
            )
        )
        state.player_pos = (0, 0)
        state.enemy_pos = (0, 0)
        self.assertEqual(choose_enemy_step(state), (1, 0))

        chase_state = GameState(
            config=build_game_config(
                layout_name="corridor",
                hazard_density="normal",
                enemy_route_cutoff_weight=0,
                enemy_chase_weight=1,
            )
        )
        chase_state.player_pos = (0, 0)
        chase_state.enemy_pos = (0, 0)
        self.assertEqual(choose_enemy_step(chase_state), (0, 0))

    def test_enemy_intensity_changes_moves_per_player_turn(self) -> None:
        base_config = build_game_config(layout_name="classic", hazard_density="normal")
        low_intensity = replace(base_config, enemy_turns_per_round=1)
        high_intensity = replace(base_config, enemy_turns_per_round=2)
        low_state = GameState(config=low_intensity)
        high_state = GameState(config=high_intensity)

        process_input(low_state, "d")
        process_input(high_state, "d")

        self.assertEqual(low_state.enemy_pos, (3, 0))
        self.assertEqual(high_state.enemy_pos, (2, 0))

    def test_enemy_behavior_stays_deterministic_for_identical_inputs(self) -> None:
        config = build_game_config(layout_name="classic", hazard_density="normal", enemy_turns_per_round=2)
        state_a = GameState(config=config)
        state_b = GameState(config=config)
        commands = ("d", "s", "a", "w", "d")

        for cmd in commands:
            process_input(state_a, cmd)
            process_input(state_b, cmd)
            self.assertEqual(self._state_key(state_a), self._state_key(state_b))
            self.assertEqual(state_a.last_message, state_b.last_message)

    def test_enemy_collision_deals_damage(self) -> None:
        state = GameState(config=build_game_config(layout_name="classic", hazard_density="normal"))
        state.enemy_pos = (2, 0)
        process_input(state, "d")
        self.assertEqual(state.hp, state.config.starting_hp - state.config.enemy_contact_damage)
        self.assertIn("[GEGNER] Kollision!", state.last_message)

    def test_enemy_collision_can_end_mission(self) -> None:
        state = GameState(config=build_game_config(layout_name="classic", hazard_density="normal"))
        state.hp = 1
        state.enemy_pos = (2, 0)
        process_input(state, "d")
        self.assertEqual(state.status, "lose")
        self.assertIn("[MISSION] Du bist ausgeschaltet.", state.last_message)

    def test_collect_three_cells_activates_extraction_for_all_layouts(self) -> None:
        for layout_name in self._layout_names():
            state = GameState(config=build_game_config(layout_name=layout_name, hazard_density="normal"))
            route = self._build_collection_route(state.config)

            for cmd in route:
                process_input(state, cmd)
                if len(state.collected_cells) < 3:
                    self.assertFalse(
                        state.extraction_active,
                        msg=f"Extraktion zu frueh aktiv in Layout {layout_name}.",
                    )

            self.assertEqual(len(state.collected_cells), 3, msg=f"Layout {layout_name} sammelt nicht 3/3.")
            self.assertTrue(state.extraction_active, msg=f"Extraktion nicht aktiv in Layout {layout_name}.")

    def test_hazard_damage_and_lose(self) -> None:
        state = GameState()
        for cmd in ("d", "s", "w", "s", "w", "s"):
            process_input(state, cmd)
            if state.status != "running":
                break
        self.assertEqual(state.status, "lose")
        self.assertLessEqual(state.hp, 0)

    def test_win_after_activation_and_reaching_extraction_for_all_layouts(self) -> None:
        for layout_name in self._layout_names():
            state = GameState(config=build_game_config(layout_name=layout_name, hazard_density="normal"))
            route = self._build_win_route(state.config)
            for cmd in route:
                process_input(state, cmd)
                if state.status != "running":
                    break

            self.assertEqual(state.status, "win", msg=f"Win-Route fehlgeschlagen fuer {layout_name}.")
            self.assertTrue(state.extraction_active, msg=f"Extraktion blieb inaktiv in Layout {layout_name}.")

    def test_time_runs_out_causes_lose_for_all_layouts(self) -> None:
        for layout_name in self._layout_names():
            safe_config = replace(
                build_game_config(layout_name=layout_name, hazard_density="normal"),
                enemy_contact_damage=0,
            )
            state = GameState(config=safe_config)
            bump_cmd = self._get_out_of_bounds_command(state.config)

            for _ in range(state.config.turn_limit):
                process_input(state, bump_cmd)
                if state.status != "running":
                    break

            self.assertEqual(state.status, "lose", msg=f"Zeitlimit endet nicht mit Lose in Layout {layout_name}.")
            self.assertEqual(state.turns_left, 0, msg=f"Zeitlimit nicht sauber auf 0 in Layout {layout_name}.")

    def test_render_shows_clear_hud_fields(self) -> None:
        state = GameState()
        output = render(state)
        self.assertIn("Kampagne", output)
        self.assertIn("HP", output)
        self.assertIn("Zuege", output)
        self.assertIn("Fortschritt", output)
        self.assertIn("Extraktion", output)
        self.assertIn("Score", output)
        self.assertIn("Best-Run", output)
        self.assertIn("G", output)

    def test_missing_save_file_does_not_break_startup(self) -> None:
        campaign = (build_game_config(layout_name="classic", hazard_density="normal"),)
        with TemporaryDirectory() as temp_dir:
            save_file = Path(temp_dir) / "missing_save.json"
            output = StringIO()
            with redirect_stdout(output):
                result = run_cli(input_stream=[], campaign_configs=campaign, save_file=save_file)
            self.assertEqual(result, 1)
            self.assertTrue(save_file.exists())
            payload = json.loads(save_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["best_run_score"], 0)

    def test_best_run_is_persisted_across_runs(self) -> None:
        campaign = (build_campaign_configs(layout_name="classic", hazard_density="normal")[0],)
        route_to_win = list(self._build_win_route(campaign[0]))
        with TemporaryDirectory() as temp_dir:
            save_file = Path(temp_dir) / "meta_progression.json"
            with redirect_stdout(StringIO()):
                first_result = run_cli(input_stream=route_to_win, campaign_configs=campaign, save_file=save_file)
            self.assertEqual(first_result, 0)

            payload = json.loads(save_file.read_text(encoding="utf-8"))
            best_after_win = payload["best_run_score"]
            self.assertGreater(best_after_win, 0)

            second_output = StringIO()
            with redirect_stdout(second_output):
                second_result = run_cli(input_stream=["q"], campaign_configs=campaign, save_file=save_file)
            self.assertEqual(second_result, 1)
            self.assertIn(f"Best-Run    : {best_after_win}", second_output.getvalue())

    def test_corrupt_save_file_is_tolerated(self) -> None:
        campaign = (build_game_config(layout_name="classic", hazard_density="normal"),)
        with TemporaryDirectory() as temp_dir:
            save_file = Path(temp_dir) / "meta_progression.json"
            save_file.write_text("{broken-json", encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                result = run_cli(input_stream=[], campaign_configs=campaign, save_file=save_file)

            self.assertEqual(result, 1)
            self.assertIn("[SAVE] Save-Datei ist korrupt.", output.getvalue())
            payload = json.loads(save_file.read_text(encoding="utf-8"))
            self.assertIn("best_run_score", payload)

    def test_events_are_tagged_consistently(self) -> None:
        state = GameState()
        process_input(state, "x")
        self.assertTrue(state.last_message.startswith("[INPUT]"))
        process_input(state, "d")
        self.assertIn("[AKTION]", state.last_message)

    def test_restart_option_restarts_session_without_process_restart(self) -> None:
        campaign = (build_game_config(layout_name="classic", hazard_density="normal"),)
        route_to_win = list(self._build_win_route(campaign[0]))
        command_stream = route_to_win + ["r"] + route_to_win
        with redirect_stdout(StringIO()):
            result = run_cli(input_stream=command_stream, campaign_configs=campaign)
        self.assertEqual(result, 0)

    def test_campaign_win_in_level_one_auto_starts_level_two(self) -> None:
        campaign = build_campaign_configs(layout_name="classic", hazard_density="normal")[:2]
        route_level_one = list(self._build_win_route(campaign[0]))
        output = StringIO()
        with redirect_stdout(output):
            result = run_cli(input_stream=route_level_one, campaign_configs=campaign)
        self.assertEqual(result, 1)
        self.assertIn("Kampagne    : Level 2/2", output.getvalue())
        self.assertIn("Starte Level 2/2", output.getvalue())

    def test_campaign_final_level_win_returns_success(self) -> None:
        campaign = build_campaign_configs(layout_name="classic", hazard_density="normal")[:2]
        route_level_one = list(self._build_win_route(campaign[0]))
        route_level_two = list(self._build_win_route(campaign[1]))
        output = StringIO()
        with redirect_stdout(output):
            result = run_cli(input_stream=route_level_one + route_level_two, campaign_configs=campaign)
        self.assertEqual(result, 0)
        self.assertIn("ERGEBNIS: WIN", output.getvalue())

    def test_full_campaign_normal_is_playable(self) -> None:
        campaign = build_campaign_configs(layout_name="classic", hazard_density="normal")
        command_stream: list[str] = []
        for level_config in campaign:
            command_stream.extend(self._build_win_route(level_config))

        output = StringIO()
        with redirect_stdout(output):
            result = run_cli(input_stream=command_stream, campaign_configs=campaign)

        self.assertEqual(result, 0)
        self.assertIn("ERGEBNIS: WIN", output.getvalue())

    def test_route_balance_report_cli_writes_min_max_per_layout(self) -> None:
        package_root = Path(__file__).resolve().parents[1]
        script_path = package_root / "scripts" / "report_route_balance.py"

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "route_balance_report.json"
            result = subprocess.run(
                ["python3", str(script_path), "--output", str(output_path), "--strict"],
                cwd=package_root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"Report-Skript fehlgeschlagen.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
            )
            self.assertTrue(output_path.is_file(), msg="Report-Datei wurde nicht erzeugt.")
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIsInstance(payload["all_routes_passed"], bool)
        self.assertEqual(payload["route_count"], 6)
        self.assertIn("summary_by_layout", payload)
        for route_payload in payload["routes"]:
            self.assertIn(route_payload["expected_status"], ("win", "lose"))
            self.assertEqual(route_payload["route_name"], route_payload["expected_status"])
            self.assertIsInstance(route_payload["profile_id"], str)
            self.assertTrue(route_payload["profile_id"])
        for layout_name in ("classic", "corridor", "crossfire"):
            self.assertIn(layout_name, payload["summary_by_layout"])
            for route_name in ("win", "lose"):
                route_summary = payload["summary_by_layout"][layout_name][route_name]
                self.assertEqual(route_summary["route_count"], 1)
                self.assertIsInstance(route_summary["min_score"], int)
                self.assertIsInstance(route_summary["max_score"], int)
                self.assertLessEqual(route_summary["min_score"], route_summary["max_score"])


if __name__ == "__main__":
    unittest.main()
