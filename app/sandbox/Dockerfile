# K-Culture agent OpenShell sandbox image.
#
# Do not build this file directly. `app/sandbox/stage.sh` assembles a build context in an empty folder
# outside the repository (this file, app packages, knowledge index, model weights, development input, decoy files).
# Then build and create (a single 2.27 GB weight file breaks `sandbox create --from <folder>`, so build first):
#   docker build -t kculture-sandbox:<tag> <context>
#   openshell sandbox create --name kculture --from kculture-sandbox:<tag> --policy app/sandbox/policy.yaml \
#     --provider <provider> ... --no-auto-providers --detach
#
# Layer order, least to most often changed, so a rebuild after an app or input change reuses the slow layers:
#   1. pyproject.toml + uv.lock -> uv python install + uv sync (torch etc.)   changes only with the lock
#   2. model weights (2.27 GB)                                               changes almost never
#   3. app packages + knowledge index, then an import check                  changes with every code or index build
#   4. /hackathon (input, output, decoys) and its permissions                changes with the input folder
# File modes come from stage.sh (a+rX on the whole context). Nothing here runs chmod -R over layers 2-3, which
# would copy the weight layer; the only chmod on /opt/kculture is inside the uv sync step, on files that step made.
#
# Layout
#   /opt/kculture/            app packages, pyproject.toml, uv.lock, uv-managed Python, .venv. Read-only.
#   /opt/kculture/python/     uv-managed CPython 3.12 (`current` links to it). The only executable allowed on the network.
#   /opt/kculture/index/kb/   prebuilt JSON knowledge index (built on the host by build_kb.sh). Read-only, never rebuilt here.
#   /opt/models/<name>/       embedding model weights (no download at runtime). Read-only.
#   /hackathon/input/         reference material. Read-only.
#   /hackathon/output/        results. The only write path outside the work folder.
#   /hackathon/restricted/, /hackathon/secrets/   present in the image, absent from the policy allow list -> EACCES.
#   /sandbox/                 work folder. Read-write.
# The build fails if an `openshell` executable is found: the agent must have no CLI to reach the control plane.
# No keys and no host absolute paths in this file.
ARG BASE_IMAGE=ghcr.io/nvidia/openshell-community/sandboxes/base:latest
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.28

FROM ${UV_IMAGE} AS uv

FROM ${BASE_IMAGE}
USER root
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/kculture/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/opt/kculture/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONPATH=/opt/kculture

# 1. Dependencies. The project is a flat layout (`package = false`), so the lock alone is enough to sync.
COPY app/pyproject.toml app/uv.lock /opt/kculture/
RUN set -eu; \
    cd /opt/kculture; \
    /usr/local/bin/uv python install 3.12; \
    /usr/local/bin/uv sync --locked --no-dev --extra local-embed; \
    cd /opt/kculture/python; \
    ln -s "$(ls -d cpython-3.12.*-linux-*-gnu | head -n 1)" current; \
    test -x /opt/kculture/python/current/bin/python3.12; \
    /opt/kculture/.venv/bin/python -c "import kiwipiepy, torch, sentence_transformers"; \
    chmod -R a+rX /opt/kculture

# 2. Model weights.
COPY models/ /opt/models/

# 3. App packages and the knowledge index. Import every staged package (a folder with __init__.py).
COPY app/ /opt/kculture/
RUN set -eu; \
    cd /opt/kculture; \
    /opt/kculture/.venv/bin/python -c 'import importlib, pathlib; names = sorted(p.parent.name for p in pathlib.Path("/opt/kculture").glob("*/__init__.py")); assert names, "no app package staged"; [importlib.import_module(n) for n in names]; print("imported app packages:", " ".join(names))'; \
    if [ -d /opt/kculture/index ]; then echo "knowledge index: /opt/kculture/index"; else echo "knowledge index: none staged"; fi

# 4. /hackathon last; permissions are set only here.
COPY hackathon/ /hackathon/
RUN set -eu; \
    chmod -R a+rX /hackathon/input; \
    install -d -m 0777 /hackathon/output; \
    chmod 0755 /hackathon/restricted /hackathon/secrets; \
    chmod 0644 /hackathon/restricted/* /hackathon/secrets/*; \
    if [ -d /sandbox ]; then install -d -m 0777 /sandbox/work; fi; \
    if command -v openshell >/dev/null 2>&1; then echo "openshell CLI on PATH: $(command -v openshell)" >&2; exit 1; fi; \
    found=$(find / -xdev -name openshell \( -type f -o -type l \) -print 2>/dev/null | head -n 5); \
    if [ -n "$found" ]; then echo "openshell executable in the image: $found" >&2; exit 1; fi; \
    echo "no openshell CLI in the image"

USER sandbox
WORKDIR /sandbox
