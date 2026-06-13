#!/bin/bash
set -e

if [[ -n "$2" ]]; then
  container="$2"
else
  container="bssmagic-runtime"
fi

echo "Loading mapping from '$1' into '$container'..."

docker exec -i $container psql -U postgres -d bssmagic < $1