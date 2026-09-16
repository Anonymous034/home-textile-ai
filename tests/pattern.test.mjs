import assert from "node:assert/strict";
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

test("pattern studio renders its upload entry point", async () => {
  const html = await render("/pattern");
  for (const text of ["花型制作", "AI PATTERN STUDIO", "点击或拖入花型图片", "选择图片"]) assert.ok(html.includes(text), text);
  assert.match(html, /href="\/dashboard\?tool=pattern"/);
  assert.match(html, /accept="image\/jpeg,image\/png,image\/webp"/);
});

test("dashboard links the pattern card to the pattern studio", async () => {
  assert.match(await render("/dashboard"), /href="\/pattern"[^>]*data-feature-link="true"[^>]*data-index="4"/);
});
