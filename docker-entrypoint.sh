#!/bin/sh
# SPLITS container entrypoint: seed the plan on first boot, then start the server.
# The server (serve.mjs) handles the boot sync and the nightly schedule itself.
set -e

DATA_DIR="${SPLITS_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# Seed the plan on first boot ONLY — never clobber an existing (coach-edited) plan,
# so image upgrades keep your training plan intact.
if [ ! -f "$DATA_DIR/plan-data.js" ]; then
  cp /app/plan-data.default.js "$DATA_DIR/plan-data.js"
  echo "seeded $DATA_DIR/plan-data.js from the shipped default"
fi

exec node serve.mjs
