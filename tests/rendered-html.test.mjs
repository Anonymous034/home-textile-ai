import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(pathname = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${pathname}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the finished product home page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>家纺AI视觉｜全链路工作台<\/title>/i);
  assert.match(html, /家纺AI视觉/);
  assert.match(html, /全链路工作台/);
  assert.doesNotMatch(html, /Your site is taking shape|codex-preview/i);
});

test("studio exposes the preset workflow", async () => {
  const response = await render("/studio");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /AI 虚拟影棚/);
  assert.doesNotMatch(html, /自定义四图融合参考图|人物身份|最终背景|动作位置/);
  assert.match(html, /模特/);
  assert.match(html, /场景/);
  assert.match(html, /构图/);
  assert.match(html, /分辨率/);
  assert.match(html, /立即生成/);
  assert.doesNotMatch(html, /融合要求|资料库预设融合|Agent Plan 立即生成|FastAPI 服务未连接/);
});

test("studio routes selected presets to the studio API", async () => {
  const source = await readFile(new URL("../app/ui/CyberStudio.tsx", import.meta.url), "utf8");
  assert.match(source, /\/api\/studio\/jobs/);
  assert.match(source, /form\.append\("main_image"/);
  assert.match(source, /form\.append\("model_preset_id"/);
  assert.match(source, /form\.append\("scene_preset_id"/);
  assert.match(source, /form\.append\("composition_id"/);
  assert.doesNotMatch(source, /reference-upload|\/api\/fusion\/jobs/);
  assert.match(source, /form\.append\("resolution", resolution\)/);
  assert.match(source, /role="alertdialog"/);
  assert.match(source, /确认将图片调整为/);
  assert.match(source, /setResolution\(pendingResolution\)/);
  assert.match(source, /className="preset-confirm"/);
  assert.match(source, /setPendingPreset\(\{ kind: presetPanel, preset \}\)/);
  assert.match(source, /放大图片/);
  assert.match(source, /确认选择/);
  assert.match(source, /presetImageUrl\(pendingPreset\.preset, "hd"\)/);
  assert.match(source, /presetImageUrl\(preset, "thumb"\)/);
  assert.match(source, /encodeURIComponent\(preset\.updated_at\)/);
  assert.match(source, /cache: "no-store"/);

  const provider = await readFile(new URL("../backend/app/providers/ark.py", import.meta.url), "utf8");
  assert.match(provider, /"supported_resolutions": \["1K", "2K", "4K"\]/);
  assert.match(provider, /"size": resolution/);
  assert.match(provider, /ImageOps\.fit\(image, \(request\.width, request\.height\)/);

  const backend = await readFile(new URL("../backend/app/main.py", import.meta.url), "utf8");
  assert.match(backend, /def hd_preset_preview/);
  assert.match(backend, /ImageFilter\.UnsharpMask/);
  assert.match(backend, /Literal\["original", "thumb", "hd"\]/);
});
