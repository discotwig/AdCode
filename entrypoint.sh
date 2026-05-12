#!/bin/sh
# On each boot, sync customer config.json files from the image into the volume.
# State files already on the volume are never touched.
for config in /app/customers_defaults/*/config.json; do
    slug=$(basename "$(dirname "$config")")
    dest_dir="/app/customers/$slug"
    mkdir -p "$dest_dir/state" "$dest_dir/campaigns"
    cp "$config" "$dest_dir/config.json"
done
exec uvicorn src.email_bot:app --host 0.0.0.0 --port 8080
