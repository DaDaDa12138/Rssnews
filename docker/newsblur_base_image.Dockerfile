# syntax=docker/dockerfile:1.4
#
# Two stages, because the image that runs the reader needs none of the toolchain
# that builds it. Every dependency ships a manylinux wheel, so the runtime stage
# drops build-essential, libpq-dev, libxml2-dev, libxslt1-dev, libjpeg-dev,
# zlib1g-dev and libffi-dev along with the uv installer.

FROM      python:3.13-slim AS builder
WORKDIR   /srv/newsblur

RUN set -ex \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        libpq-dev \
        libjpeg-dev \
        zlib1g-dev \
        libxml2-dev \
        libxslt1-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Create virtual environment. It lives at a fixed path so the runtime stage can
# copy the whole tree instead of reinstalling anything.
RUN uv venv --python 3.13 /venv
ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV="/venv"

# requirements.lock is generated from requirements.txt with
#   uv pip compile config/requirements.txt --universal --python-version 3.13 \
#       --generate-hashes -o config/requirements.lock
# Installing the lock with --require-hashes means a rebuild either reproduces the
# reviewed dependency set or fails, instead of quietly resolving a new release.
COPY config/requirements.txt config/requirements.lock /srv/newsblur/
RUN uv pip install --require-hashes -r requirements.lock

# esbuild minifies the reader bundle at collectstatic time. It is a single static
# binary, which keeps a Node toolchain (and node_modules) out of the runtime image.
ARG ESBUILD_VERSION=0.25.5
RUN set -ex \
    && curl -sSL "https://registry.npmjs.org/@esbuild/linux-x64/-/linux-x64-${ESBUILD_VERSION}.tgz" \
        | tar -xz -C /usr/local/bin --strip-components=2 package/bin/esbuild \
    && chmod +x /usr/local/bin/esbuild \
    && /usr/local/bin/esbuild --version


FROM      python:3.13-slim
WORKDIR   /srv/newsblur
ENV       PYTHONPATH=/srv/newsblur

# Only what the running processes touch: TLS roots for outbound feed fetches, curl
# for the health probes, tzdata for the configured timezone and patch because the
# supervisor applies one at boot.
RUN set -ex \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata \
        patch \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
COPY --from=builder /usr/local/bin/esbuild /usr/local/bin/esbuild
ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV="/venv"
