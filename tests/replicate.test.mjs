import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(pathname) {
  const { default: worker } = await import("../dist/server/index.js");
  const response = await worker.fetch(new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }), { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } }, { waitUntil() {}, passThroughOnException() {} });
  assert.equal(response.status, 200);
  return response.text();
}

test("replica has one reference input, explicit output sizing and truthful status", async () => {
  const html = await render("/replicate");
  for (const copy of ["爆款复刻画布", "上传主产品图", "上传一张参考图", "仅允许一张", "跟随参考图", "去除参考图文字", "生成后需人工检查", "确认尺寸并生成 1 张"]) assert.ok(html.includes(copy), copy);
  assert.doesNotMatch(html, /multiple=""|当前账户余额|消耗积分|LATENCY|AI CORE: STABLE|RENDER COMPLETE/);
  assert.match(html, /class="replica-generate"[^>]*disabled=""/);
  assert.equal((html.match(/type="file"/g) ?? []).length, 4);
});

test("replica submits real files and polls the independent API, with no simulated percentage", async () => {
  const source = await readFile(new URL("../app/ui/ViralReplicaLab.tsx", import.meta.url), "utf8");
  assert.match(source, /body.append\("reference_image", reference.file\)/);
  assert.match(source, /Idempotency-Key/);
  assert.match(source, /api\/replicate\/jobs/);
  assert.match(source, /api\/replicate\/prepare/);
  assert.match(source, /api\/replicate\/connectivity\?refresh=true/);
  assert.match(source, /安全重试 · 请求尚未提交/);
  assert.match(source, /job\.phase/);
  assert.match(source, /files.length !== 1/);
  assert.doesNotMatch(source, /setInterval|setProgress|ARK_API_KEY|setCompleted/);
});
