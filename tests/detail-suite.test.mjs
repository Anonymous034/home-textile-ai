import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

async function loadTs(file) {
  const code = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  return import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
}
const model = await loadTs("../app/detail-page/models.ts");
const api = await loadTs("../app/detail-page/api.ts");
const images = [{ id: "main_1", role: "main" }, { id: "detail_2", role: "detail" }];
const input = { ...model.initialInput, productName: "全棉床品" };

test("reorder preserves stable identities, data and immutable original", () => {
  const plan = model.templatePlan(input, images);
  const original = structuredClone(plan.items);
  const result = model.reorderPlan(plan.items, plan.items[0].id, plan.items[4].id);
  assert.deepEqual(plan.items, original);
  assert.deepEqual(result.map(item => item.order), [1, 2, 3, 4, 5, 6]);
  assert.equal(result[4].id, original[0].id);
  assert.deepEqual(new Set(result.map(item => item.id)), new Set(original.map(item => item.id)));
  assert.equal(result[4].visualDescription, original[0].visualDescription);
});

test("template is explicit and contains requested count with valid source references", () => {
  const plan = model.templatePlan(input, images);
  assert.equal(plan.source, "template");
  assert.equal(plan.items.length, input.imageCount);
  assert.equal(model.validatePlan(plan, images.map(image => image.id)), "");
  assert.match(model.validateInput({ ...input, productName: "  " }, images), /产品名称/);
  assert.match(model.validateInput(input, [{ ...images[0], role: "scene" }]), /主图/);
});

test("plan validation rejects missing sources, duplicate IDs and malformed AI data", () => {
  const plan = model.templatePlan(input, images);
  assert.match(model.validatePlan(plan, []), /素材/);
  plan.items[1].id = plan.items[0].id;
  assert.match(model.validatePlan(plan, images.map(image => image.id)), /重复/);
  for (const bad of [null, {}, { ...plan, items: [null] }, { ...plan, items: [{ id: "x" }] }]) {
    assert.notEqual(model.validatePlan(bad, []), "");
  }
});

test("result links are confined to service download namespace", () => {
  assert.equal(api.resultUrl("https://untrusted.example/image.png"), undefined);
  assert.equal(api.resultUrl("//untrusted.example/image.png"), undefined);
  assert.equal(api.resultUrl("/api/detail/../../admin"), undefined);
  assert.match(api.resultUrl("/api/detail/tasks/id/export"), /\/api\/detail\/tasks\/id\/export$/);
  assert.equal(api.resultUrl("/api/detail/tasks/id/export"), "/api/detail/tasks/id/export");
});

test("ambiguous render submission raises uncertain error and never auto-reposts", async (t) => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new TypeError("offline"); };
  t.after(() => { globalThis.fetch = original; });
  await assert.rejects(api.detailApi.render({ taskId: "t1" }), error => error instanceof api.DetailApiError && error.uncertain);
  assert.equal(calls, 1);
});

test("task polling uses GET and rejects unrelated task response", async (t) => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ id: "other", status: "running", items: [{ planItemId: "card1", status: "queued" }] }));
  };
  t.after(() => { globalThis.fetch = original; });
  await assert.rejects(api.detailApi.task("requested"), /任务状态格式/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method ?? "GET", "GET");
  assert.match(calls[0].url, /tasks\/requested$/);
});

test("unimplemented endpoint is explicit rather than simulated success", async (t) => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("missing", { status: 404 });
  t.after(() => { globalThis.fetch = original; });
  await assert.rejects(api.detailApi.plan(input, images, "key"), error => !error.uncertain && /尚未就绪/.test(error.message));
});

test("standard JSON example matches runtime contract", () => {
  const plan = JSON.parse(readFileSync(new URL("../docs/detail-plan.example.json", import.meta.url), "utf8"));
  assert.equal(plan.items.length, plan.input.imageCount);
  assert.equal(model.validatePlan(plan, ["image_main", "image_detail", "image_scene"]), "");
});

test("original page settings support twelve images and reject mismatched order/count", () => {
  const plan = model.templatePlan({ ...input, imageCount: 12, aspectRatio: "9:16", resolution: "1K" }, images);
  assert.equal(model.validatePlan(plan, images.map(image => image.id)), "");
  plan.items[0].order = 2;
  assert.match(model.validatePlan(plan, images.map(image => image.id)), /顺序/);
  plan.items[0].order = 1;
  plan.input.imageCount = 8;
  assert.match(model.validatePlan(plan, images.map(image => image.id)), /张数/);
});

test("configuration rejection is definite and shows actionable safe backend message", async (t) => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { message: "请配置 DETAIL_PLAN_MODEL", uncertain: false } }), { status: 503 });
  t.after(() => { globalThis.fetch = original; });
  await assert.rejects(api.detailApi.plan(input, images, "key"), error => !error.uncertain && /DETAIL_PLAN_MODEL/.test(error.message));
});

test("ambiguous planning recovery only queries the original request", async (t) => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, method: options.method ?? "GET" }); return new Response(JSON.stringify({ state: "running" })); };
  t.after(() => { globalThis.fetch = original; });
  assert.equal((await api.detailApi.planStatus("original-plan")).state, "running");
  assert.equal(calls[0].method, "GET");
  assert.match(calls[0].url, /\/plans\/original-plan$/);
});
