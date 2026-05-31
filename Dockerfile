# syntax=docker/dockerfile:1.7
#
# QwenPaw all-in-one HFS runtime image.
# Pattern A / artifact-at-build-time.
#
# Development:
#   docker build -t qwenpaw-all-in-one-hfs:dev --build-arg QWENPAW_VERSION=1.1.9 .
#
# Release-style:
#   docker build \
#     --build-arg BASE_IMAGE_REF='node:22-slim@sha256:<digest>' \
#     --build-arg QWENPAW_VERSION='1.1.9' \
#     --build-arg QWENPAW_PACKAGE_SHA256='73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63' \
#     --build-arg UV_VERSION='0.7.20' \
#     --build-arg QWENPAW_UPSTREAM_REF='2d9527bb097f9b09428190f80e1f3fd44f2ff453' \
#     -t qwenpaw-all-in-one-hfs:release .

ARG BASE_IMAGE_REF=node:22-slim
FROM ${BASE_IMAGE_REF} AS runtime

ARG BASE_IMAGE_REF
ARG QWENPAW_VERSION=1.1.9
ARG QWENPAW_PACKAGE_SHA256=73ff2ca8b22dbfd6d233b678fb1de040bb41a1bff8b2b4091ecde866e1e57f63
ARG UV_VERSION=0.7.20
ARG QWENPAW_UPSTREAM_REF=2d9527bb097f9b09428190f80e1f3fd44f2ff453
ARG DEBIAN_FRONTEND=noninteractive

ENV QWENPAW_HFS_BUILD_BASE_IMAGE_REF=${BASE_IMAGE_REF}
ENV QWENPAW_HFS_BUILD_QWENPAW_VERSION=${QWENPAW_VERSION}
ENV QWENPAW_HFS_BUILD_QWENPAW_PACKAGE_SHA256=${QWENPAW_PACKAGE_SHA256}
ENV QWENPAW_HFS_BUILD_UV_VERSION=${UV_VERSION}
ENV QWENPAW_HFS_BUILD_QWENPAW_UPSTREAM_REF=${QWENPAW_UPSTREAM_REF}

ENV NODE_ENV=production \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    VIRTUAL_ENV=/home/user/.venv \
    PATH="/home/user/.venv/bin:/home/user/.local/bin:${PATH}" \
    PORT=7860 \
    QWENPAW_PORT=8088 \
    QWENPAW_WORKING_DIR=/data/qwenpaw/working \
    QWENPAW_SECRET_DIR=/data/qwenpaw/secrets \
    QWENPAW_BACKUP_DIR=/data/qwenpaw/backups \
    QWENPAW_RUNNING_IN_CONTAINER=1 \
    QWENPAW_TELEMETRY_OPT_OUT=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium \
    QWENPAW_DISABLED_CHANNELS=imessage

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates curl git gettext-base tini \
      python3 python3-pip python3-venv build-essential libssl-dev \
      nginx supervisor procps netcat-openbsd \
      dbus dbus-x11 xvfb \
      chromium chromium-sandbox \
      fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-cjk fonts-liberation \
      libnss3 libglib2.0-0 libdrm2 libgbm1 libasound2 \
      libx11-xcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxi6 libxtst6 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Chromium must run inside the container sandbox model used by QwenPaw/Playwright.
RUN if [ -x /usr/bin/chromium ]; then \
      sed -i 's/^CHROMIUM_FLAGS=""/CHROMIUM_FLAGS="--no-sandbox"/' /usr/bin/chromium || true; \
    fi

RUN set -eux; \
    if ! getent passwd 1000 >/dev/null; then \
      useradd -m -u 1000 user; \
    fi; \
    mkdir -p /home/user; \
    chown 1000:1000 /home/user; \
    mkdir -p \
      /data/qwenpaw/working \
      /data/qwenpaw/secrets \
      /data/qwenpaw/backups \
      /data/var/logs \
      /tmp/qwenpaw-run \
      /home/user/app \
    && chown -R 1000:1000 /data /tmp/qwenpaw-run /home/user

USER 1000
WORKDIR /home/user/app

RUN python3 -m venv /home/user/.venv \
    && python -m pip install --upgrade pip wheel \
    && if [ "${UV_VERSION}" = "latest" ]; then \
         python -m pip install uv; \
       else \
         python -m pip install "uv==${UV_VERSION}"; \
       fi \
    && mkdir -p /tmp/qwenpaw-dist \
    && python -m pip download --no-deps --dest /tmp/qwenpaw-dist "qwenpaw==${QWENPAW_VERSION}" \
    && artifact="$(find /tmp/qwenpaw-dist -maxdepth 1 -type f | sort | head -n 1)" \
    && test -n "$artifact" \
    && if [ -n "${QWENPAW_PACKAGE_SHA256}" ] && [ "${QWENPAW_PACKAGE_SHA256}" != "dev-placeholder" ]; then \
         printf '%s  %s\n' "${QWENPAW_PACKAGE_SHA256}" "$artifact" | sha256sum -c -; \
       else \
         echo "WARNING: QWENPAW_PACKAGE_SHA256 is not set; development build is not release-pinned"; \
       fi \
    && uv pip install --python /home/user/.venv/bin/python --no-cache-dir "$artifact" \
    && rm -rf /tmp/qwenpaw-dist

COPY --chown=1000:1000 docker/ /home/user/app/docker/
COPY --chown=1000:1000 hfs-dev.toml /home/user/app/hfs-dev.toml

RUN chmod +x /home/user/app/docker/entrypoint.sh \
             /home/user/app/docker/healthcheck.sh

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD /home/user/app/docker/healthcheck.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/home/user/app/docker/entrypoint.sh"]
