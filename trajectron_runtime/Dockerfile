# Author-compatible, CPU-only inference environment. No ROS or host Python.
# Both base images are pinned to their linux/amd64 manifest digests.
FROM python:3.6.15-buster@sha256:08c787fde0ef9fac8d9244e0d49939ce3dfca27198fac37ac2748c2d3c8fc987 AS wheels

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m pip install --no-cache-dir \
    pip==21.3.1 setuptools==59.6.0 wheel==0.37.1
COPY requirements.lock /build/requirements.lock
# ncls 0.0.51 has no cp36 Linux wheel; build it using the compiler already
# present in the builder image. Cython is a build dependency only.
RUN python -m pip install --no-cache-dir numpy==1.16.4 Cython==0.29.36 \
    && python -m pip wheel --no-deps --no-build-isolation \
       --wheel-dir=/wheelhouse \
       --find-links=https://download.pytorch.org/whl/torch_stable.html \
       -r /build/requirements.lock \
    && python -m pip download --only-binary=:all: --no-deps \
       --dest=/wheelhouse pip==21.3.1 setuptools==59.6.0 wheel==0.37.1 \
    && cd /wheelhouse && sha256sum *.whl > SHA256SUMS

# The old headless OpenCV wheel still links to GLib. Copy the three required
# libraries from the digest-pinned Debian builder; no archived apt repository
# or host OS package installation is needed. Preserve origin versions/hashes.
RUN mkdir -p /runtime-libs /runtime-meta \
    && cp -L /usr/lib/x86_64-linux-gnu/libglib-2.0.so.0 \
       /usr/lib/x86_64-linux-gnu/libgthread-2.0.so.0 \
       /lib/x86_64-linux-gnu/libpcre.so.3 /runtime-libs/ \
    && dpkg-query -W libglib2.0-0 libpcre3 > /runtime-meta/shared-library-packages.txt \
    && cd /runtime-libs && sha256sum * > /runtime-meta/shared-library-sha256.txt

FROM python:3.6.15-slim-buster@sha256:d59ee182c4629dd33b240b9bac1a6ff44276e79e66117eba17aed4016845d3b2 AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/trajectron-src/trajectron MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib XDG_CACHE_HOME=/tmp/cache HOME=/tmp/home \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
COPY --from=wheels /runtime-libs/ /usr/lib/x86_64-linux-gnu/
COPY --from=wheels /runtime-meta/ /opt/runtime/
COPY requirements.lock /opt/runtime/requirements.lock
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    ldconfig \
    && python -m pip install --no-index --find-links=/wheelhouse \
       pip==21.3.1 setuptools==59.6.0 wheel==0.37.1 \
    && python -m pip install --no-index --find-links=/wheelhouse --no-deps \
       -r /opt/runtime/requirements.lock \
    && python -m pip check \
    && cp /wheelhouse/SHA256SUMS /opt/runtime/wheel-sha256.txt \
    && python -m pip freeze --all > /opt/runtime/installed-packages.txt
COPY verify_runtime.py /opt/runtime/verify_runtime.py
WORKDIR /opt/runtime
# Numeric identity works without adding or modifying any host account.
USER 1000:1000
CMD ["python", "/opt/runtime/verify_runtime.py"]
