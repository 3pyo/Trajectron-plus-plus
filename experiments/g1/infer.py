#!/usr/bin/env python3
"""Run the author's unchanged int_ee checkpoint on measured G1 history."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import sys

import numpy as np
import torch

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / "trajectron"))
from adapter import DT, DT_NS, build_observation, debug_future, read_rows
from model.model_registrar import ModelRegistrar
from model.trajectron import Trajectron


def write_json(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def load_model(env):
    directory = SOURCE / "experiments/nuScenes/models/int_ee"
    hyperparams = json.loads((directory / "config.json").read_text())
    if hyperparams["use_map_encoding"] or hyperparams["incl_robot_node"]:
        raise ValueError("this runner requires the original map-free, robot-free int_ee configuration")
    registrar = ModelRegistrar(str(directory), "cpu")
    registrar.load_models(12)
    loaded_keys = sorted(registrar.model_dict.keys())
    model = Trajectron(registrar, hyperparams, None, "cpu")
    model.set_environment(env)
    model.set_annealing_params()
    if sorted(registrar.model_dict.keys()) != loaded_keys:
        raise RuntimeError("checkpoint mismatch: newly initialized model modules")
    registrar.eval()
    return model, hyperparams, directory


def predict_scene(model, hyperparams, scene, audit, num_samples=20, seed=0):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    scene.calculate_scene_graph(model.env.attention_radius, hyperparams["edge_addition_filter"],
                                hyperparams["edge_removal_filter"])
    t = scene.timesteps - 1
    kwargs = dict(scene=scene, timesteps=np.array([t]), ph=6,
                  min_future_timesteps=0, min_history_timesteps=audit["min_history_points"] - 1,
                  full_dist=False)
    with torch.no_grad():
        sampled = model.predict(num_samples=num_samples, z_mode=False, gmm_mode=False, **kwargs)
        modal = model.predict(num_samples=1, z_mode=True, gmm_mode=True, **kwargs)
    output = []
    for node, prediction in sorted(sampled.get(t, {}).items(), key=lambda item: item[0].id):
        info = audit["nodes"][node.id]
        if not info["prediction_eligible"]:
            continue
        most_likely = modal[t][node]
        if prediction.shape != (1, num_samples, 6, 2) or most_likely.shape != (1, 1, 6, 2):
            raise RuntimeError("unexpected prediction shape: " + repr(prediction.shape))
        if not np.isfinite(prediction).all() or not np.isfinite(most_likely).all():
            raise RuntimeError("nonfinite prediction")
        output.append({
            "node_id": node.id, "experiment_id": info["experiment_id"],
            "tracking_session_id": info["tracking_session_id"], "person_id": info["person_id"],
            "segment_index": info["segment_index"], "frame_id": audit["frame_id"],
            "prediction_time_ns": audit["prediction_time_ns"],
            "future_timestamps_ns": [audit["prediction_time_ns"] + (i + 1) * DT_NS for i in range(6)],
            "history_timestamps_ns": info["timestamps_ns"],
            "history_positions": [state[:2] for state in info["states"]],
            "samples_xy": prediction[0].tolist(), "most_likely_xy": most_likely[0, 0].tolist()})
    if not output:
        raise RuntimeError("model returned no eligible pedestrian predictions")
    return output


def plot_predictions(predictions, audit, future, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    artifacts = []
    for index, prediction in enumerate(predictions):
        info = audit["nodes"][prediction["node_id"]]
        history = np.asarray(prediction["history_positions"])
        current = history[-1]
        samples = np.asarray(prediction["samples_xy"])
        mode = np.asarray(prediction["most_likely_xy"])
        fig, (ax, timing) = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"width_ratios": [1.7, 1]})
        # Show simultaneous observed pedestrians as interaction context.
        for node_id, neighbor in audit["nodes"].items():
            if node_id != prediction["node_id"] and neighbor["last_timestep"] == len(audit["grid_timestamps_ns"]) - 1:
                xy = np.asarray(neighbor["states"])[:, :2]
                ax.plot(xy[:, 0], xy[:, 1], color="0.7", linewidth=1)
        ax.plot(history[:, 0], history[:, 1], "o-", color="black", label="Observed (resampled)", markersize=4)
        for i, sample in enumerate(samples[:50]):
            connected = np.vstack([current, sample])
            ax.plot(connected[:, 0], connected[:, 1], color="tab:blue", alpha=0.15,
                    label="Predicted samples" if i == 0 else None)
        connected = np.vstack([current, mode])
        ax.plot(connected[:, 0], connected[:, 1], "o-", color="tab:orange", label="Most likely", markersize=4)
        for step, point in enumerate(mode, 1):
            ax.annotate("+{:.1f}s".format(step * DT), point, xytext=(4, 4), textcoords="offset points", fontsize=7)
        ax.scatter(*current, s=90, marker="*", color="red", label="Prediction time", zorder=5)
        debug = future.get(prediction["node_id"])
        if debug:
            observed = np.array([point if point is not None else [np.nan, np.nan] for point in debug["positions"]])
            connected = np.vstack([current, observed])
            ax.plot(connected[:, 0], connected[:, 1], "--o", color="tab:green", markersize=3,
                    label="Subsequent tracker observations (debug only)")
        ax.set(xlabel="{} x [m]".format(audit["frame_id"]), ylabel="{} y [m]".format(audit["frame_id"]),
               title="{} / person {}".format(prediction["experiment_id"], prediction["person_id"]))
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7)
        time = [(stamp - audit["prediction_time_ns"]) / 1e9 for stamp in info["timestamps_ns"]]
        velocity = np.asarray(info["states"])[:, 2:4]
        timing.plot(time, velocity[:, 0], "o-", label="vx")
        timing.plot(time, velocity[:, 1], "o-", label="vy")
        timing.axvline(0, color="red", linestyle="--")
        timing.set(xlabel="Time relative to prediction [s]", ylabel="Derived velocity [m/s]",
                   title="Observation-only input: {} points".format(len(time)))
        timing.grid(alpha=0.25)
        timing.legend()
        fig.tight_layout()
        stem = "pedestrian_{:03d}".format(index)
        for suffix in ("png", "svg"):
            path = Path(output) / (stem + "." + suffix)
            fig.savefig(str(path), dpi=170)
            artifacts.append(path.name)
        plt.close(fig)
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="case_logger frames.jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--experiment-id", required=True)
    timing = parser.add_mutually_exclusive_group()
    timing.add_argument("--end-offset-sec", type=float, help="cutoff relative to first pedestrian metadata row")
    timing.add_argument("--prediction-time-ns", type=int, help="absolute cutoff; snaps backwards to a measured state")
    parser.add_argument("--observation-start-ns", type=int, help="e.g. RAG t1; never widen this boundary")
    parser.add_argument("--max-gap-sec", type=float, default=0.5)
    parser.add_argument("--min-history-points", type=int, default=3)
    parser.add_argument("--target-session")
    parser.add_argument("--target-person-id", type=int)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--debug-future", action="store_true", help="plot future tracker positions AFTER inference")
    args = parser.parse_args()
    if args.samples < 1 or args.samples > 2000:
        parser.error("samples must be 1..2000")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if list(output.iterdir()):
        parser.error("output must be empty")
    torch.set_num_threads(2)
    rows = read_rows(args.input)
    pedestrian_rows = [r for r in rows if r.get("persons")]
    if not pedestrian_rows:
        parser.error("no pedestrian rows")
    first = min(r["timestamp_ns"] for r in pedestrian_rows)
    cutoff = args.prediction_time_ns
    if cutoff is None:
        cutoff = (first + int(round(args.end_offset_sec * 1e9)) if args.end_offset_sec is not None
                  else max(r["timestamp_ns"] for r in pedestrian_rows))
    env, scene, audit = build_observation(
        rows, args.experiment_id, cutoff, args.observation_start_ns, args.max_gap_sec,
        args.min_history_points, args.target_session, args.target_person_id)
    model, hyperparams, model_dir = load_model(env)
    predictions = predict_scene(model, hyperparams, scene, audit, args.samples, args.seed)
    # Future diagnostic extraction happens only after both prediction passes finish.
    future = debug_future(rows, audit) if args.debug_future else {}
    write_json(output / "observation.json", audit)
    write_json(output / "predictions.json", {"schema_version": "g1.trajectron.predictions.v1", "predictions": predictions})
    if args.debug_future:
        write_json(output / "debug-future.json", future)
    plots = plot_predictions(predictions, audit, future, output)
    import matplotlib
    import pandas
    report = {
        "status": "passed", "prediction_count": len(predictions), "samples_per_pedestrian": args.samples,
        "horizon_steps": 6, "horizon_sec": 3.0, "dt_sec": DT, "seed": args.seed,
        "checkpoint": "int_ee/model_registrar-12.pt", "device": "cpu",
        "checkpoint_sha256": hashlib.sha256((model_dir / "model_registrar-12.pt").read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256((model_dir / "config.json").read_bytes()).hexdigest(),
        "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        "runtime": {"python": platform.python_version(), "torch": torch.__version__,
                    "numpy": np.__version__, "pandas": pandas.__version__, "matplotlib": matplotlib.__version__},
        "inference_input": "observation.json only; no future states or map/robot node",
        "debug_future_enabled": args.debug_future, "plots": plots,
        "requested_cutoff_ns": audit["requested_cutoff_ns"], "prediction_time_ns": audit["prediction_time_ns"],
        "all_predictions_finite": True, "checkpoint_modules_reused_without_new_modules": True}
    write_json(output / "inference-report.json", report)
    print("G1_INFERENCE=PASSED")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
