import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Windows launcher owns processes and keeps the site available during AI outages", async () => {
  const source = await readFile(new URL("../start-ai-studio.ps1", import.meta.url), "utf8");
  for (const marker of ["backend.pid.json", "frontend.pid.json", "startedUtcTicks", "/api/health/live", "/api/health/ready", "/api/replicate/connectivity?refresh=true", "Test-Port", "taskkill.exe /PID"]) assert.ok(source.includes(marker), marker);
  assert.match(source, /--host", "127\.0\.0\.1"/);
  assert.doesNotMatch(source, /--reload/);
  assert.match(source, /\$aiReady = \[bool\]\$connectivity\.connected/);
  assert.match(source, /if \(-not \$aiReady\) \{\s*Write-Warning/);
  assert.match(source, /The backend will retry automatically/);
  assert.match(source, /if \(\$aiReady\) \{\s*Write-Host "Local website and AI service are ready/);
});

test("Windows stop script validates process identity before tree termination", async () => {
  const source = await readFile(new URL("../stop-ai-studio.ps1", import.meta.url), "utf8");
  assert.match(source, /StartTime\.ToUniversalTime\(\)\.Ticks -eq/);
  assert.match(source, /taskkill\.exe \/PID \$process\.Id \/T \/F/);
});
