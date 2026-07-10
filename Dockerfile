# SPLITS — one image: Node serves the dashboard + API, Python runs the Garmin sync.
#
# garminconnect>=0.3.6 needs Python >=3.12, so we base on python:3.12 and bring in
# just the Node runtime binary (serve.mjs is zero-dependency — no npm / node_modules
# needed at runtime; the archive API uses the built-in node:sqlite, stable in Node 24).
# Both stages are Debian bookworm, so the binary is compatible.
FROM node:24-bookworm-slim AS node
FROM python:3.12-slim-bookworm

# Node runtime (binary only) + tzdata (so TZ and the nightly schedule work) + certs.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first for better layer caching.
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# App code, including vendor/ (the React UMD builds + self-hosted fonts). These
# vendored client assets ship as application code in the image — never in the
# /data volume — so the cockpit renders with outbound network access removed.
# .dockerignore must NOT exclude vendor/. Personal data files ARE excluded there;
# they live in the /data volume, never in the image.
COPY . .
RUN chmod +x docker-entrypoint.sh

ENV SPLITS_DATA_DIR=/data \
    SPLITS_PYTHON=python3 \
    PORT=8000 \
    NODE_ENV=production

EXPOSE 8000
VOLUME ["/data"]

ENTRYPOINT ["./docker-entrypoint.sh"]
