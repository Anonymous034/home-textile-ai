import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

async function sources(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) result.push(...await sources(path));
    else if (/\.(ts|tsx)$/.test(entry.name)) result.push(path);
  }
  return result;
}

test("frontend source does not hard-code a visitor-local API server", async () => {
  const app = fileURLToPath(new URL("../app/", import.meta.url));
  for (const path of await sources(app)) {
    if (path.startsWith(join(app, "api") + "\\") || path.startsWith(join(app, "api") + "/")) continue;
    const source = await readFile(path, "utf8");
    assert.doesNotMatch(source, /(?:127\.0\.0\.1|localhost):8000|ws:\/\/localhost/, `${path} still points to a visitor-local backend`);
  }
});
