import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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

test("upscale renders batch upload, mode controls and an honest initial state", async () => {
  const html = await render("/upscale");
  for (const text of ["一键高清｜家纺AI视觉工作台", "高清图片画布", "上传或拖入图片", "处理方式", "清晰增强", "高清放大", "预计消耗积分", "转高清", "已连接 Seedream"]) assert.ok(html.includes(text), text);
  assert.match(html, /type="file" multiple=""/);
  assert.match(html, /name="enhance-mode" checked="" value="清晰增强"/);
  assert.match(html, /class="template-generate"[^>]*disabled=""/);
  assert.doesNotMatch(html, /处理完成|24ms|高清图片已生成/);
});

test("dashboard provides a real link for the tenth card", async () => {
  const html = await render("/dashboard");
  assert.match(html, /href="\/upscale"[^>]*data-feature-link="true"[^>]*data-index="9"/);
});

test("batch uploads have count, size, duplicate and resource cleanup guards", async () => {
  const source = await readFile(new URL("../app/ui/UpscaleLab.tsx", import.meta.url), "utf8");
  assert.match(source, /MAX_IMAGES = 12/);
  assert.match(source, /MAX_BYTES = 20 \* 1024 \* 1024/);
  assert.match(source, /next.length >= MAX_IMAGES/);
  assert.match(source, /item.fingerprint === fingerprint/);
  assert.match(source, /URL.revokeObjectURL\(removed.url\)/);
  assert.match(source, /urls.forEach\(\(url\) => URL.revokeObjectURL\(url\)\)/);
  assert.match(source, /handleImageError/);
  assert.doesNotMatch(source, /setInterval/);
  assert.match(source, /fetch\(`\$\{API\}\/api\/upscale\/generate`/);
  assert.match(source, /form\.append\("image"/);
  assert.match(source, /form\.append\("mode"/);
  assert.match(source, /AbortSignal\.timeout/);
  assert.doesNotMatch(source, /aria-label="切换创作工具"/);
  assert.doesNotMatch(source, /<details className="upscale-tool-menu"/);
});
