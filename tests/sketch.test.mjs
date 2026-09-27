import assert from "node:assert/strict";
import test from "node:test";
import { validateSketchUpload } from "../app/ui/sketch-upload.ts";

async function render(pathname) {
  const { default: worker } = await import("../dist/server/index.js");
  const response = await worker.fetch(new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }), { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } }, { waitUntil() {}, passThroughOnException() {} });
  assert.equal(response.status, 200);
  return response.text();
}

test("sketch page renders A/B inputs and reference controls without a large canvas heading", async () => {
  const html = await render("/sketch");
  for (const label of ["画稿生图｜家纺AI视觉工作台", "画稿生图画布", "上传或拖入 A 版", "上传或拖入 B 版", "选择纯色", "上传或拖入参考图", "品类", "面料", "工艺", "图片比例", "分辨率", "由 Agent Plan 图片服务生成"]) assert.ok(html.includes(label), `Missing ${label}`);
  assert.match(html, /<option selected="">3:4<\/option>/);
  assert.match(html, /<option selected="">1K<\/option>/);
  assert.match(html, /class="template-generate"[^>]*disabled=""/);
  assert.match(html, /aria-label="上传或拖入参考图"/);
  assert.equal((html.match(/<h1/g) ?? []).length, 1);
  assert.doesNotMatch(html, /24ms|图片已生成|生成完成/);
});

test("dashboard links the sketch card to its own workspace", async () => {
  assert.match(await render("/dashboard"), /href="\/sketch"[^>]*data-feature-link="true"[^>]*data-index="6"/);
});

test("sketch uploads validate counts, type and file size before creating previews", () => {
  const valid = { type: "image/png", size: 1024 };
  assert.equal(validateSketchUpload([valid], 0, 1), "");
  assert.match(validateSketchUpload([valid, valid], 0, 1), /一张/);
  assert.equal(validateSketchUpload([valid], 11, 12), "");
  assert.match(validateSketchUpload([valid, valid], 11, 12), /12 张/);
  assert.match(validateSketchUpload([{ type: "image/svg+xml", size: 1024 }], 0, 1), /JPG/);
  assert.match(validateSketchUpload([{ ...valid, size: 0 }], 0, 1), /不能为空/);
  assert.equal(validateSketchUpload([{ ...valid, size: 20 * 1024 * 1024 }], 0, 1), "");
  assert.match(validateSketchUpload([{ ...valid, size: 20 * 1024 * 1024 + 1 }], 0, 1), /20MB/);
});
