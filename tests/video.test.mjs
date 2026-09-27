import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("video duration is a manually adjustable 5–15 second range", async () => {
  const source = await readFile(new URL("../app/ui/VideoLab.tsx", import.meta.url), "utf8");
  assert.match(source, /type="range"/);
  assert.match(source, /min=\{5\}/);
  assert.match(source, /max=\{15\}/);
  assert.match(source, /step=\{1\}/);
  assert.doesNotMatch(source, /<option>5 秒<\/option>/);
  assert.match(source, /<option>480P<\/option><option>720P<\/option><option>1080P<\/option>/);
});
