$ErrorActionPreference = "Stop"
$name = "edgeseek-seekdb"
$exists = docker ps -a --filter "name=^/$name$" --format "{{.Names}}"
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not available." }
if ($exists) {
  $running = docker inspect $name --format "{{.State.Running}}"
  if ($running -ne "true") { docker start $name | Out-Null }
} else {
  docker run -d --name $name --restart unless-stopped `
    --publish 127.0.0.1:2882:2881 `
    --mount type=volume,source=edgeseek-seekdb-data,target=/var/lib/seekdb `
    --env CPU_COUNT=2 --env MEMORY_LIMIT=2G oceanbase/seekdb:latest | Out-Null
}

for ($attempt = 0; $attempt -lt 90; $attempt++) {
  $logs = docker logs --tail 40 $name 2>&1 | Out-String
  if ($logs -match "SQL ready") { Write-Host "EdgeSeek seekdb is ready on 127.0.0.1:2882."; exit 0 }
  $running = docker inspect $name --format "{{.State.Running}}"
  if ($running -ne "true") { throw "EdgeSeek seekdb exited during startup. Check: docker logs $name" }
  Start-Sleep -Seconds 1
}
throw "Timed out waiting for seekdb SQL readiness. Check: docker logs $name"
