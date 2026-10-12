"""Validate dependencies and checkpoint initialization; no experiment inference."""

import argparse
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="/opt/trajectron-src")
    parser.add_argument("--output", default="/results")
    args = parser.parse_args()
    source = Path(args.source)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    import pkg_resources

    requirements = [line.strip() for line in Path("/opt/runtime/requirements.lock").read_text().splitlines()
                    if line.strip() and not line.startswith("#")]
    pkg_resources.require(requirements)
    versions = {name: pkg_resources.get_distribution(name).version
                for name in (line.split("==")[0] for line in requirements)}
    for module in ["torch", "numpy", "pandas", "scipy", "matplotlib", "seaborn", "sklearn",
                   "orjson", "ncls", "dill", "tqdm", "cv2", "pyquaternion", "environment",
                   "model.trajectron", "model.online.online_trajectron", "model.dataset",
                   "model.dynamics", "evaluation", "visualization"]:
        importlib.import_module(module)
        checks.append("import:" + module)
    import numpy as np
    import torch
    import dill
    import orjson
    from ncls import NCLS
    from environment import Environment, Scene, Node
    from model.model_registrar import ModelRegistrar
    from model.trajectron import Trajectron

    assert sys.version_info[:3] == (3, 6, 15)
    assert torch.__version__ == "1.4.0+cpu"
    assert torch.version.cuda is None
    assert not torch.cuda.is_available()
    torch.set_num_threads(2)
    assert torch.mm(torch.eye(2), torch.eye(2)).equal(torch.eye(2))
    index = NCLS(np.array([0, 5], dtype=np.int64), np.array([3, 7], dtype=np.int64),
                 np.array([0, 1], dtype=np.int64))
    assert sorted(hit[2] for hit in index.find_overlap(2, 6)) == [0, 1]
    assert json.loads(orjson.dumps({"ok": True})) == {"ok": True}
    checks.extend(["cpu-tensor-operation", "ncls-compiled-extension", "orjson-compiled-extension"])

    scene = Scene(timesteps=1, dt=0.5, name="dependency-check-only")
    env = Environment(node_type_list=["VEHICLE", "PEDESTRIAN"], standardization={}, scenes=[scene])
    assert dill.loads(dill.dumps(env)).scenes[0].dt == 0.5
    checks.append("environment-dill-roundtrip")

    model_dir = source / "experiments/nuScenes/models/int_ee"
    checkpoint = model_dir / "model_registrar-12.pt"
    hyperparams = json.loads((model_dir / "config.json").read_text())
    registrar = ModelRegistrar(str(model_dir), "cpu")
    registrar.load_models(12)
    loaded_keys = sorted(registrar.model_dict.keys())
    assert any(name.startswith("PEDESTRIAN/") for name in loaded_keys)
    assert any(name.startswith("VEHICLE/") for name in loaded_keys)
    trajectron = Trajectron(registrar, hyperparams, None, "cpu")
    trajectron.set_environment(env)
    trajectron.set_annealing_params()
    assert sorted(registrar.model_dict.keys()) == loaded_keys, "unexpected randomly initialized modules"
    assert {node_type.name for node_type in trajectron.node_models_dict} == {"VEHICLE", "PEDESTRIAN"}
    parameters = list(registrar.parameters())
    assert parameters and all(torch.isfinite(param).all().item() for param in parameters)
    checks.extend(["checkpoint-12-load", "both-node-models-initialized", "all-checkpoint-parameters-finite"])

    for relative in ["experiments/nuScenes/evaluate.py", "experiments/pedestrians/evaluate.py",
                     "trajectron/test_online.py"]:
        script = source / relative
        print("ENTRYPOINT_IMPORT_CHECK=" + relative, flush=True)
        subprocess.check_call([sys.executable, str(script), "--help"], cwd=str(script.parent))
        checks.append("entrypoint-help:" + relative)

    # Opening without O_TRUNC performs no mutation, even if the mount were wrong.
    try:
        descriptor = os.open(str(source / "README.md"), os.O_WRONLY)
    except OSError as error:
        assert error.errno == errno.EROFS, "source must be mounted read-only"
    else:
        os.close(descriptor)
        raise AssertionError("source mount is writable")
    checks.append("source-mount-read-only")

    for line in Path("/opt/runtime/shared-library-sha256.txt").read_text().splitlines():
        expected, filename = line.split()
        assert sha256(Path("/usr/lib/x86_64-linux-gnu") / filename) == expected
    checks.append("shared-library-hashes")
    for name in ["wheel-sha256.txt", "installed-packages.txt", "shared-library-packages.txt",
                 "shared-library-sha256.txt"]:
        shutil.copyfile(str(Path("/opt/runtime") / name), str(output / name))
    report = {"status": "passed", "scope": "CPU dependencies, imports and checkpoint initialization only",
              "experiment_inference_performed": False, "adapter_implemented": False,
              "python": platform.python_version(), "python_executable": sys.executable,
              "uid": os.getuid(), "gid": os.getgid(), "cuda": torch.version.cuda,
              "versions": versions, "checks": checks, "checkpoint": str(checkpoint),
              "checkpoint_sha256": sha256(checkpoint), "checkpoint_module_count": len(loaded_keys),
              "checkpoint_parameter_count": sum(param.numel() for param in parameters),
              "checkpoint_module_keys": loaded_keys,
              "source_sha256": {relative: sha256(source / relative) for relative in
                                ["requirements.txt", "experiments/nuScenes/models/int_ee/config.json",
                                 "trajectron/model/model_registrar.py", "trajectron/model/trajectron.py"]}}
    with (output / "dependency-report.json").open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("DEPENDENCY_VERIFICATION=PASSED", flush=True)
    print(json.dumps({"checks": len(checks), "checkpoint_modules": len(loaded_keys),
                      "report": str(output / "dependency-report.json")}), flush=True)


if __name__ == "__main__":
    main()
