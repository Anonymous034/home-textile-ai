import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

async function render(pathname) {
  const { default: worker } = await import("../dist/server/index.js");
  const response = await worker.fetch(
    new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(response.status, 200);
  return response.text();
}

test("local edit renders upload and output settings without an oversized empty heading", async () => {
  const html = await render("/local-edit");
  for (const text of ["局部编辑｜强视觉ai生图", "局部编辑画布", "编辑图片", "上传或拖入图片", "生成范围", "只选区（默认）", "图片比例", "分辨率", "预计消耗积分", "系统会先生成严格的英文提示词 JSON"]) assert.ok(html.includes(text), text);
  assert.match(html, /<option value="selected_only" selected="">只选区（默认）<\/option>/);
  assert.match(html, /<option selected="">3:4<\/option>/);
  assert.match(html, /<option selected="">1K<\/option>/);
  assert.match(html, /<span>返回<\/span>/);
  assert.doesNotMatch(html, /返回工作台|精修完成|24ms/);
});

test("dashboard eighth card links to the local edit page", async () => {
  assert.match(await render("/dashboard"), /href="\/local-edit"[^>]*data-feature-link="true"[^>]*data-index="7"/);
});

test("local edit submits the original, monochrome mask and Chinese requirement", async () => {
  const source = await readFile(new URL("../app/ui/LocalEditLab.tsx", import.meta.url), "utf8");
  assert.match(source, /<canvas[^>]+local-edit-mask-layer/);
  assert.match(source, /fillStyle = "#000"/);
  assert.match(source, /strokeStyle = "#fff"/);
  assert.match(source, /form\.append\("image"/);
  assert.match(source, /form\.append\("mask"/);
  assert.match(source, /form\.append\("requirement"/);
  assert.match(source, /\/api\/local-edit\/generate/);
  assert.match(source, /确认选区/);
});
