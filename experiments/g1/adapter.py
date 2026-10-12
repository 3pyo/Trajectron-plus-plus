"""Measured G1 tracks -> observation-only Trajectron scenes (Python 3.6)."""

import bisect
from collections import Counter
import json
import math
from pathlib import Path

DT_NS = 500000000
DT = 0.5
STATE_COLUMNS = [(kind, axis) for kind in ("position", "velocity", "acceleration")
                 for axis in ("x", "y")]
# Match experiments/nuScenes/process_data.py; retain both checkpoint node types.
STANDARDIZATION = {
    "PEDESTRIAN": {
        "position": {axis: {"mean": 0, "std": 1} for axis in ("x", "y")},
        "velocity": {axis: {"mean": 0, "std": 2} for axis in ("x", "y")},
        "acceleration": {axis: {"mean": 0, "std": 1} for axis in ("x", "y")}},
    "VEHICLE": {
        "position": {axis: {"mean": 0, "std": 80} for axis in ("x", "y")},
        "velocity": {axis: {"mean": 0, "std": 15} for axis in ("x", "y", "norm")},
        "acceleration": {axis: {"mean": 0, "std": 4} for axis in ("x", "y", "norm")},
        "heading": {axis: {"mean": 0, "std": math.pi if axis == "°" else 1}
                    for axis in ("x", "y", "°", "d°")}}}


def read_rows(path):
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema_version") not in ("case_logger.v1", "case_logger.offline.v1"):
                raise ValueError("unsupported schema at line {}".format(line_no))
            if not isinstance(row.get("timestamp_ns"), int):
                raise ValueError("timestamp_ns must be an integer at line {}".format(line_no))
            rows.append(row)
    if not rows:
        raise ValueError("no metadata rows")
    return rows


def stamp_ns(stamp):
    if not isinstance(stamp, dict):
        raise ValueError("missing track or measurement stamp")
    sec, nano = stamp.get("sec"), stamp.get("nanosec")
    if not isinstance(sec, int) or not isinstance(nano, int) or not 0 <= nano < 1000000000:
        raise ValueError("invalid ROS stamp")
    return sec * 1000000000 + nano


def measured_tracks(rows, start_ns, end_ns):
    """Never use rows recorded after cutoff, nor future-dated matched tracks."""
    tracks, frames, counts = {}, set(), Counter()
    for row in rows:
        if not start_ns <= row["timestamp_ns"] <= end_ns:
            counts["rows_outside_window"] += 1
            continue
        tracking = row.get("tracking") or {}
        for person in row.get("persons", []):
            track = person.get("track") or {}
            if not track:
                counts["missing_track"] += 1
                continue
            ts = stamp_ns(track.get("track_stamp"))
            if not start_ns <= ts <= end_ns:
                counts["track_stamp_outside_window"] += 1
                continue
            if track.get("track_status") != "confirmed" or track.get("missed_frames") != 0:
                counts["not_confirmed_measurement"] += 1
                continue
            if stamp_ns(track.get("last_measurement_stamp")) != ts:
                counts["measurement_not_updated"] += 1
                continue
            frame = tracking.get("frame_id")
            session = track.get("tracking_session_id") or tracking.get("tracking_session_id")
            person_id = person.get("person_id")
            if not frame or not session or not isinstance(person_id, int):
                raise ValueError("measured track needs frame, session and integer person_id")
            if tracking.get("tracking_session_id") not in (None, session):
                raise ValueError("person/array tracking session mismatch")
            frames.add(frame)
            position = track.get("position") or {}
            xy = [float(position[axis]) for axis in ("x", "y")]
            if not all(math.isfinite(value) for value in xy):
                counts["nonfinite_position"] += 1
                continue
            key = (session, person_id)
            by_time = tracks.setdefault(key, {})
            if ts in by_time:
                if by_time[ts] != xy:
                    raise ValueError("conflicting positions for the same track stamp")
                counts["duplicate_track_stamp"] += 1
            else:
                by_time[ts] = xy
                counts["accepted_measurements"] += 1
    if len(frames) > 1:
        raise ValueError("mixed tracking coordinate frames: " + repr(sorted(frames)))
    return tracks, next(iter(frames)) if frames else None, dict(counts)


def interpolate(by_time, timestamps, max_gap_ns):
    """No extrapolation; each interpolation returns its observed support stamps."""
    source_ts = sorted(by_time)
    values, supports = [], []
    for ts in timestamps:
        i = bisect.bisect_left(source_ts, ts)
        if i < len(source_ts) and source_ts[i] == ts:
            values.append(by_time[ts])
            supports.append([ts])
        elif i == 0 or i == len(source_ts) or source_ts[i] - source_ts[i - 1] > max_gap_ns:
            values.append(None)
            supports.append([])
        else:
            left, right = source_ts[i - 1], source_ts[i]
            ratio = float(ts - left) / (right - left)
            values.append([a + ratio * (b - a) for a, b in zip(by_time[left], by_time[right])])
            supports.append([left, right])
    return values, supports


def build_observation(rows, experiment_id, requested_cutoff_ns, observation_start_ns=None,
                      max_gap_sec=0.5, min_history_points=3, target_session=None, target_person_id=None):
    """Clip BEFORE interpolation, differentiation and scene graph construction."""
    import numpy as np
    import pandas as pd
    from environment import Environment, Scene, Node, derivative_of

    if not experiment_id or not 2 <= min_history_points <= 9:
        raise ValueError("experiment ID required; min_history_points must be 2..9")
    if not math.isfinite(max_gap_sec) or max_gap_sec <= 0:
        raise ValueError("max_gap_sec must be positive and finite")
    start = max(requested_cutoff_ns - 8 * DT_NS,
                observation_start_ns if observation_start_ns is not None else requested_cutoff_ns - 8 * DT_NS)
    if start >= requested_cutoff_ns:
        raise ValueError("observation start must precede cutoff")
    tracks, frame, counts = measured_tracks(rows, start, requested_cutoff_ns)
    if not tracks:
        raise ValueError("no confirmed, freshly measured tracks in observation window")
    eligible = [ts for (session, person), samples in tracks.items() for ts in samples
                if (target_session is None or session == target_session)
                and (target_person_id is None or person == target_person_id)]
    if not eligible:
        raise ValueError("target pedestrian has no eligible measurements")
    # Snap backwards only; arbitrary end offsets never invent a current observation.
    cutoff = max(eligible)
    # With no explicit t1, use a full four seconds before the ACTUAL cutoff.
    # An explicit observation boundary is always respected.
    start = max(cutoff - 8 * DT_NS,
                observation_start_ns if observation_start_ns is not None else cutoff - 8 * DT_NS)
    tracks, frame, counts = measured_tracks(rows, start, cutoff)
    n = min(9, (cutoff - start) // DT_NS + 1)
    grid = [cutoff - (n - 1 - i) * DT_NS for i in range(n)]
    if n < min_history_points:
        raise ValueError("observation window too short for minimum history")
    scene = Scene(timesteps=n, dt=DT, name=experiment_id)
    env = Environment(node_type_list=["VEHICLE", "PEDESTRIAN"],
                      standardization=STANDARDIZATION, scenes=[scene])
    env.attention_radius = {
        (env.NodeType.PEDESTRIAN, env.NodeType.PEDESTRIAN): 10.0,
        (env.NodeType.PEDESTRIAN, env.NodeType.VEHICLE): 20.0,
        (env.NodeType.VEHICLE, env.NodeType.PEDESTRIAN): 20.0,
        (env.NodeType.VEHICLE, env.NodeType.VEHICLE): 30.0}
    env.robot_type = env.NodeType.VEHICLE
    metadata = {}
    for (session, person), samples in sorted(tracks.items()):
        positions, supports = interpolate(samples, grid, int(round(max_gap_sec * 1e9)))
        # Internal gaps become separate nodes, never zero positions or bridged history.
        runs, run_start = [], None
        for i in range(n + 1):
            valid = i < n and positions[i] is not None
            if valid and run_start is None:
                run_start = i
            if not valid and run_start is not None:
                if i - run_start >= 2:
                    runs.append((run_start, i))
                run_start = None
        for run_index, (a, b) in enumerate(runs):
            xy = np.asarray(positions[a:b], dtype=float)
            velocity = np.column_stack([derivative_of(xy[:, axis], DT) for axis in (0, 1)])
            accel = np.column_stack([derivative_of(velocity[:, axis], DT) for axis in (0, 1)])
            state = np.column_stack([xy, velocity, accel])
            node_id = json.dumps([experiment_id, session, person, run_index], ensure_ascii=True, separators=(",", ":"))
            node = Node(env.NodeType.PEDESTRIAN, node_id,
                        pd.DataFrame(state, columns=pd.MultiIndex.from_tuples(STATE_COLUMNS)), first_timestep=a)
            scene.nodes.append(node)
            metadata[node_id] = {
                "experiment_id": experiment_id, "tracking_session_id": session, "person_id": person,
                "segment_index": run_index, "first_timestep": a, "last_timestep": b - 1,
                "timestamps_ns": grid[a:b], "states": state.tolist(),
                "interpolation_support_ns": supports[a:b],
                "prediction_eligible": b == n and b - a >= min_history_points
                and (target_session is None or session == target_session)
                and (target_person_id is None or person == target_person_id)}
    if not any(item["prediction_eligible"] for item in metadata.values()):
        raise ValueError("no current track has sufficient contiguous measured history")
    audit = {
        "experiment_id": experiment_id, "frame_id": frame,
        "requested_cutoff_ns": requested_cutoff_ns, "prediction_time_ns": cutoff,
        "cutoff_snap_back_sec": (requested_cutoff_ns - cutoff) / 1e9,
        "observation_start_ns": start, "grid_timestamps_ns": grid, "dt_sec": DT,
        "min_history_points": min_history_points, "max_interpolation_gap_sec": max_gap_sec,
        "measurement_filter": "confirmed; missed_frames=0; last_measurement_stamp=track_stamp",
        "state_source": "resampled track.position -> derivative_of(position) -> derivative_of(velocity)",
        "selection_counts": counts, "nodes": metadata}
    return env, scene, audit


def debug_future(rows, audit, horizon=6):
    """Separate post-prediction diagnostic, never a scene/model input."""
    cutoff = audit["prediction_time_ns"]
    tracks, frame, _ = measured_tracks(rows, cutoff, cutoff + horizon * DT_NS)
    if frame not in (None, audit["frame_id"]):
        raise ValueError("debug future uses a different coordinate frame")
    future_grid = [cutoff + (i + 1) * DT_NS for i in range(horizon)]
    result = {}
    for node_id, info in audit["nodes"].items():
        if not info["prediction_eligible"]:
            continue
        samples = tracks.get((info["tracking_session_id"], info["person_id"]), {})
        xy, supports = interpolate(samples, future_grid, int(round(audit["max_interpolation_gap_sec"] * 1e9)))
        result[node_id] = {"timestamps_ns": future_grid, "positions": xy,
                           "interpolation_support_ns": supports,
                           "label": "subsequent measured tracker positions; not independent ground truth"}
    return result
