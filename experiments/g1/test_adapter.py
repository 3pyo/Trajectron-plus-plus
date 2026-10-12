"""Container-only regressions for temporal isolation and real checkpoint prediction."""

import argparse
import copy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / "trajectron"))
from adapter import DT_NS, build_observation, interpolate, measured_tracks, read_rows
from infer import load_model, predict_scene

BASE = 1783504685000000000


def stamp(ns):
    return {"sec": ns // 1000000000, "nanosec": ns % 1000000000}


def make_rows(count=25, people=1):
    result = []
    for i in range(count):
        ns = BASE + i * DT_NS
        persons = []
        for person in range(1, people + 1):
            persons.append({"person_id": person, "track": {
                "tracking_session_id": "session", "track_stamp": stamp(ns),
                "last_measurement_stamp": stamp(ns), "track_status": "confirmed", "missed_frames": 0,
                "position": {"x": i * 0.5 + person * 2, "y": person * 2.0},
                "velocity": {"x": -99999, "y": 99999}, "velocity_valid": False}})
        result.append({"schema_version": "case_logger.v1", "timestamp_ns": ns,
                       "tracking": {"frame_id": "map", "tracking_session_id": "session"}, "persons": persons})
    return result


class AdapterTests(unittest.TestCase):
    def test_position_derivatives_ignore_tracker_velocity(self):
        _, _, audit = build_observation(make_rows(), "constant", BASE + 8 * DT_NS)
        info = next(iter(audit["nodes"].values()))
        state = np.asarray(info["states"])
        np.testing.assert_allclose(state[:, 2], 1.0)
        np.testing.assert_allclose(state[:, 3:], 0.0)
        self.assertEqual(len(state), 9)

    def test_two_schemas_and_duplicate_matched_track(self):
        rows = make_rows(9)
        rows[-1]["schema_version"] = "case_logger.offline.v1"
        rows.append(copy.deepcopy(rows[-1]))
        _, _, audit = build_observation(rows, "duplicates", BASE + 8 * DT_NS)
        self.assertEqual(audit["selection_counts"]["duplicate_track_stamp"], 1)
        self.assertEqual(len(next(iter(audit["nodes"].values()))["states"]), 9)

    def test_coasting_and_stale_measurements_are_not_input(self):
        rows = make_rows(10)
        rows[-1]["persons"][0]["track"]["track_status"] = "coasting"
        rows[-1]["persons"][0]["track"]["missed_frames"] = 1
        rows[-1]["persons"][0]["track"]["position"]["x"] = 1e9
        tracks, _, counts = measured_tracks(rows, BASE, BASE + 9 * DT_NS)
        self.assertEqual(len(next(iter(tracks.values()))), 9)
        self.assertEqual(counts["not_confirmed_measurement"], 1)
        rows[-1]["persons"][0]["track"]["track_status"] = "confirmed"
        rows[-1]["persons"][0]["track"]["missed_frames"] = 0
        rows[-1]["persons"][0]["track"]["last_measurement_stamp"] = stamp(BASE)
        _, _, counts = measured_tracks(rows, BASE, BASE + 9 * DT_NS)
        self.assertEqual(counts["measurement_not_updated"], 1)

    def test_no_extrapolation_or_long_gap_interpolation(self):
        data = {BASE: [0, 0], BASE + 2 * DT_NS: [2, 0]}
        values, supports = interpolate(data, [BASE - 1, BASE + DT_NS, BASE + 2 * DT_NS + 1], DT_NS)
        self.assertEqual(values, [None, None, None])
        self.assertEqual(supports, [[], [], []])

    def test_internal_gap_splits_nodes(self):
        rows = [r for i, r in enumerate(make_rows(9)) if i not in (3, 4)]
        _, _, audit = build_observation(rows, "gap", BASE + 8 * DT_NS)
        nodes = list(audit["nodes"].values())
        self.assertEqual([item["first_timestep"] for item in nodes], [0, 5])
        self.assertEqual([len(item["states"]) for item in nodes], [3, 4])
        self.assertEqual([item["prediction_eligible"] for item in nodes], [False, True])

    def test_explicit_observation_start_is_respected(self):
        _, scene, audit = build_observation(make_rows(), "short", BASE + 8 * DT_NS, BASE + 5 * DT_NS)
        self.assertEqual(scene.timesteps, 4)
        self.assertEqual(audit["grid_timestamps_ns"][0], BASE + 5 * DT_NS)
        for item in audit["nodes"].values():
            self.assertTrue(all(ts >= BASE + 5 * DT_NS for support in item["interpolation_support_ns"] for ts in support))

    def test_mixed_coordinate_frames_fail(self):
        rows = make_rows(9)
        rows[-1]["tracking"]["frame_id"] = "odom"
        with self.assertRaisesRegex(ValueError, "mixed tracking"):
            build_observation(rows, "mixed", BASE + 8 * DT_NS)

    def test_ids_separate_sessions_and_experiments(self):
        rows = make_rows(9)
        for row in rows:
            person = copy.deepcopy(row["persons"][0])
            person["track"]["tracking_session_id"] = "second_session"
            row["persons"].append(person)
            row["tracking"].pop("tracking_session_id", None)
        _, _, audit = build_observation(rows, "first_experiment", BASE + 8 * DT_NS)
        _, _, other = build_observation(rows, "second_experiment", BASE + 8 * DT_NS)
        self.assertEqual(len(audit["nodes"]), 2)
        self.assertTrue(set(audit["nodes"]).isdisjoint(other["nodes"]))

    def test_conflicting_duplicate_stamp_fails(self):
        rows = make_rows(9)
        extra = copy.deepcopy(rows[-1])
        extra["persons"][0]["track"]["position"]["x"] += 1
        rows.append(extra)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            build_observation(rows, "conflict", BASE + 8 * DT_NS)

    def test_future_matched_track_and_late_metadata_are_excluded(self):
        rows = make_rows(10)
        rows[-1]["timestamp_ns"] = BASE + 8 * DT_NS
        tracks, _, counts = measured_tracks(rows, BASE, BASE + 8 * DT_NS)
        self.assertEqual(len(next(iter(tracks.values()))), 9)
        self.assertEqual(counts["track_stamp_outside_window"], 1)
        rows[-1]["timestamp_ns"] = BASE + 10 * DT_NS
        rows[-1]["persons"][0]["track"]["track_stamp"] = stamp(BASE + 8 * DT_NS)
        rows[-1]["persons"][0]["track"]["last_measurement_stamp"] = stamp(BASE + 8 * DT_NS)
        tracks, _, _ = measured_tracks(rows, BASE, BASE + 8 * DT_NS)
        self.assertEqual(len(next(iter(tracks.values()))), 9)

    def test_cutoff_snaps_backwards_to_real_measurement(self):
        _, _, audit = build_observation(make_rows(), "snap", BASE + 8 * DT_NS + 100000000)
        self.assertEqual(audit["prediction_time_ns"], BASE + 8 * DT_NS)
        self.assertEqual(audit["cutoff_snap_back_sec"], 0.1)
        self.assertEqual(len(audit["grid_timestamps_ns"]), 9)

    def test_missing_history_and_bad_window_fail(self):
        with self.assertRaisesRegex(ValueError, "sufficient|short"):
            build_observation(make_rows(2), "short", BASE + DT_NS)
        with self.assertRaisesRegex(ValueError, "precede"):
            build_observation(make_rows(), "bad", BASE + 8 * DT_NS, BASE + 8 * DT_NS)

    def test_target_selection_preserves_neighbor_nodes(self):
        _, scene, audit = build_observation(make_rows(9, 2), "target", BASE + 8 * DT_NS, target_person_id=2)
        self.assertEqual(len(scene.nodes), 2)
        eligible = [n["person_id"] for n in audit["nodes"].values() if n["prediction_eligible"]]
        self.assertEqual(eligible, [2])


class CheckpointTests(unittest.TestCase):
    def compare_future_mutation(self, rows, experiment, cutoff):
        altered = copy.deepcopy(rows)
        for row in altered:
            if row["timestamp_ns"] > cutoff:
                for person in row.get("persons", []):
                    person["track"]["position"]["x"] = 1e8
                    person["track"]["position"]["y"] = -1e8
        env, scene, audit = build_observation(rows, experiment, cutoff)
        model, params, _ = load_model(env)
        original = predict_scene(model, params, scene, audit, num_samples=5, seed=19)
        env2, scene2, audit2 = build_observation(altered, experiment, cutoff)
        self.assertEqual(audit["nodes"], audit2["nodes"])
        model.set_environment(env2)
        changed = predict_scene(model, params, scene2, audit2, num_samples=5, seed=19)
        self.assertEqual(original, changed)
        np.testing.assert_array_equal(scene.temporal_scene_graph.adj_cube, scene2.temporal_scene_graph.adj_cube)
        np.testing.assert_array_equal(scene.temporal_scene_graph.edge_scaling, scene2.temporal_scene_graph.edge_scaling)
        self.assertTrue(all(ts <= audit["prediction_time_ns"] for info in audit["nodes"].values()
                            for support in info["interpolation_support_ns"] for ts in support))
        return original

    def test_real_checkpoint_multi_pedestrian_future_isolation(self):
        result = self.compare_future_mutation(make_rows(25, 2), "two_pedestrians", BASE + 8 * DT_NS)
        self.assertEqual(len(result), 2)

    def test_real_g1_samples_future_isolation(self):
        for case in ("safe_2", "danger_2"):
            with self.subTest(case=case):
                rows = read_rows(Path("/fixtures") / case / "metadata/frames.jsonl")
                cutoff = min(row["timestamp_ns"] for row in rows) + 6000000000
                result = self.compare_future_mutation(rows, case, cutoff)
                self.assertEqual(len(result), 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/results/tests.json")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"status": "passed" if result.wasSuccessful() else "failed", "tests_run": result.testsRun,
              "failures": [name.id() for name, _ in result.failures],
              "errors": [name.id() for name, _ in result.errors], "skipped": len(result.skipped)}
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
