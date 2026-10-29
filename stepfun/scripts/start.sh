#!/usr/bin/env sh
set -eu
"$(dirname "$0")/start-seekdb.sh"
cd "$(dirname "$0")/.."
npm run dev
