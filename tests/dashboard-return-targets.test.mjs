import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const returnTargets = [
  ["CyberStudio.tsx", "studio"],
  ["ViralReplicaLab.tsx", "replicate"],
  ["DetailPageLab.tsx", "detail-page"],
  ["DetailSuiteWorkflow.tsx", "detail-page"],
  ["TemplateLab.tsx", "template"],
  ["PatternLab.tsx", "pattern"],
  ["VideoLab.tsx", "video"],
  ["SketchLab.tsx", "sketch"],
  ["LocalEditLab.tsx", "local-edit"],
  ["BuyerShowLab.tsx", "buyer-show"],
  ["UpscaleLab.tsx", "upscale"],
];

test("creation pages return to their matching dashboard card", async () => {
  for (const [file, tool] of returnTargets) {
    const source = await readFile(new URL(`../app/ui/${file}`, import.meta.url), "utf8");
    assert.ok(source.includes(`/dashboard?tool=${tool}`), `${file} should return to ${tool}`);
  }

  const dashboard = await readFile(new URL("../app/ui/WorkbenchDashboard.tsx", import.meta.url), "utf8");
  assert.match(dashboard, /new URLSearchParams\(window\.location\.search\)\.get\("tool"\)/);
  for (const [, tool] of returnTargets) assert.ok(dashboard.includes(`id: "${tool}"`), `Missing dashboard tool ${tool}`);
});
