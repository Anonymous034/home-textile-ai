import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("creation tool panel headers are static titles without dropdown navigation", async () => {
  const files = ["TemplateLab.tsx", "LocalEditLab.tsx", "SketchLab.tsx", "BuyerShowLab.tsx", "UpscaleLab.tsx"];
  for (const file of files) {
    const source = await readFile(new URL(`../app/ui/${file}`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /aria-label="切换创作工具"/, file);
    assert.doesNotMatch(source, /<details className="(?:local-edit|sketch|buyer|upscale)-tool-menu"/, file);
  }
});
