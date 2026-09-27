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

test("buyer-show renders the reference controls with truthful preview status", async () => {
  const html = await render("/buyer-show");
  for (const label of ["买家秀｜强视觉ai生图", "买家秀画布", "产品图片", "更真实", "更精致", "生成张数", "产品信息", "产品名称", "核心卖点", "图片比例", "分辨率", "补充说明", "生成图像"] ) {
    assert.ok(html.includes(label), `Missing ${label}`);
  }
  assert.match(html, /name="buyer-style"/);
  assert.match(html, /name="buyer-count"/);
  assert.match(html, /<option selected="">3:4<\/option>/);
  assert.match(html, /<option selected="">1K<\/option>/);
  assert.match(html, /class="template-generate"[^>]*disabled=""/);
  assert.match(html, /href="\/dashboard\?tool=buyer-show"[^>]*>[\s\S]*?<span>返回<\/span>/);
  assert.doesNotMatch(html, /24ms|图片已生成|快速套用成熟版式|构建高转化详情页/);
  assert.doesNotMatch(html, /生成可用于图像引擎|已生成 1 张生活场景方案|PLAN JSON|PLAN FIRST/);
});

test("dashboard links buyer-show card to the new page", async () => {
  const html = await render("/dashboard");
  assert.match(html, /href="\/buyer-show"[^>]*data-feature-link="true"[^>]*data-index="8"/);
  assert.match(html, /aria-label="查看买家秀"/);
});

test("buyer-show validates uploads and releases local image URLs", async () => {
  const source = await readFile(new URL("../app/ui/BuyerShowLab.tsx", import.meta.url), "utf8");
  assert.match(source, /20 \* 1024 \* 1024/);
  assert.match(source, /URL\.revokeObjectURL\(product.url\)/);
  assert.match(source, /onError=\{imageError\}/);
  assert.match(source, /role="alert"/);
  assert.match(source, /count \* 8/);
  assert.doesNotMatch(source, /setInterval/);
  assert.match(source, /BuyerPlanDialog/);
});

test("buyer-show API keeps planning and confirmed rendering as separate idempotent requests", async () => {
  const source = await readFile(new URL("../app/buyer-show/api.ts", import.meta.url), "utf8");
  assert.match(source, /\/api\/buyer-show\/assets/);
  assert.match(source, /\/api\/buyer-show\/plans/);
  assert.match(source, /Idempotency-Key/);
  assert.match(source, /application\/json/);
  assert.match(source, /queryBuyerPlan/);
  assert.match(source, /createBuyerTask/);
  assert.match(source, /queryBuyerTask/);
  assert.match(source, /\/api\/buyer-show\/tasks/);
  assert.match(source, /encodeURIComponent\(planId\)/);
  assert.doesNotMatch(source, /ARK_API_KEY|BUYER_PLAN_API_KEY/);
});

test("buyer-show plan dialog exposes editable text and requires explicit confirmation", async () => {
  const source = await readFile(new URL("../app/ui/BuyerPlanDialog.tsx", import.meta.url), "utf8");
  for (const label of ["图片展示内容与顺序", "英文渲染 Prompt", "Negative Prompt", "确认方案并生成", "下载方案 JSON"]) assert.ok(source.includes(label), `Missing ${label}`);
  assert.match(source, /phase === "review"/);
  assert.match(source, /createBuyerTask\(input, planId, plan, id\)/);
  assert.doesNotMatch(source, /setInterval/);
});
