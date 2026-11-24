#!/bin/sh
# Copy the library into the integration (HA installs no extra packages).
set -e
cd "$(dirname "$0")/.."
dst=custom_components/philips_titan/titan
rm -rf "$dst" && mkdir -p "$dst"
for f in __init__.py client.py models.py pairing.py wol.py; do
  cp "src/philips_titan/$f" "$dst/$f"
done
echo "Bibliothek nach $dst kopiert"
