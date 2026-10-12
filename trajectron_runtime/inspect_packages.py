#!/usr/bin/env python3
"""Inspect public wheel metadata without installing anything on the host."""

import json
import urllib.request


PACKAGES = {
    "numpy": "1.16.4", "pandas": "0.25.1", "scipy": "1.3.1",
    "matplotlib": "3.1.3", "seaborn": "0.9.0", "scikit-learn": "0.22.1",
    "orjson": "2.1.4", "ncls": "0.0.51", "dill": "0.3.1.1", "tqdm": "4.45.0",
    "opencv-python-headless": "4.1.1.26", "pyquaternion": "0.9.5",
}

for name, version in PACKAGES.items():
    with urllib.request.urlopen("https://pypi.org/pypi/{}/{}/json".format(name, version),
                                timeout=30) as response:
        metadata = json.load(response)
    compatible = [item["filename"] for item in metadata["urls"]
                  if item["filename"].endswith(".whl") and
                  (("cp36" in item["filename"] and "x86_64" in item["filename"] and
                    "manylinux" in item["filename"]) or
                   "none-any" in item["filename"])]
    print(json.dumps({"package": name, "version": version, "wheels": compatible,
                      "requires_dist": metadata["info"].get("requires_dist")}))
