#!/usr/bin/env sh
set -eu
name=edgeseek-seekdb
if docker inspect "$name" >/dev/null 2>&1; then
  running=$(docker inspect "$name" --format '{{.State.Running}}')
  if [ "$running" != true ]; then docker start "$name" >/dev/null; fi
else
  docker run -d --name "$name" --restart unless-stopped \
    --publish 127.0.0.1:2882:2881 \
    --mount type=volume,source=edgeseek-seekdb-data,target=/var/lib/seekdb \
    --env CPU_COUNT=2 --env MEMORY_LIMIT=2G oceanbase/seekdb:latest >/dev/null
fi
attempt=0
while [ "$attempt" -lt 90 ]; do
  if docker logs --tail 40 "$name" 2>&1 | grep -q "SQL ready"; then
    echo "EdgeSeek seekdb is ready on 127.0.0.1:2882."
    exit 0
  fi
  running=$(docker inspect "$name" --format '{{.State.Running}}')
  [ "$running" = true ] || { echo "seekdb exited; check: docker logs $name" >&2; exit 1; }
  sleep 1
  attempt=$((attempt + 1))
done
echo "Timed out; check: docker logs $name" >&2
exit 1
