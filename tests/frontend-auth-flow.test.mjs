import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("homepage shows the workbench before a visitor selects a feature", async () => {
  const homepage = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const workbench = await readFile(new URL("../app/ui/AuthenticatedWorkbench.tsx", import.meta.url), "utf8");
  assert.match(homepage, /<AuthenticatedWorkbench\s*\/>/);
  assert.match(workbench, /useState\(false\).*gateOpen|\[gateOpen, setGateOpen\] = useState\(false\)/);
  assert.match(workbench, /<WorkbenchDashboard/);
  assert.match(workbench, /\{gateOpen && \(/);
});

test("login form always offers the 123 demo path and visible hint", async () => {
  const form = await readFile(new URL("../app/ui/DemoLoginForm.tsx", import.meta.url), "utf8");
  assert.match(form, /phone\.trim\(\) === "123"/);
  assert.match(form, /const DEMO_LOGIN_HINT = "演示登录：手机号填 123，验证码填 123456/);
  assert.match(form, /demo-login__message.*DEMO_LOGIN_HINT/);
  assert.doesNotMatch(form, /NEXT_PUBLIC_DEMO_LOGIN_ENABLED/);
});

test("authentication calls use the frontend origin and local proxy protects public demo login", async () => {
  const sources = [
    "DemoLoginForm.tsx",
    "AuthenticatedWorkbench.tsx",
    "WorkbenchDashboard.tsx",
    "UserMenu.tsx",
  ];
  for (const source of sources) {
    const text = await readFile(new URL(`../app/ui/${source}`, import.meta.url), "utf8");
    assert.match(text, /\/api\/auth\//);
    assert.doesNotMatch(text, /NEXT_PUBLIC_STUDIO_API/);
  }
  const proxy = await readFile(new URL("../app/api/auth/[...path]/route.ts", import.meta.url), "utf8");
  assert.match(proxy, /STUDIO_API_INTERNAL_URL/);
  assert.match(proxy, /DEMO_LOGIN_PUBLIC_ENABLED/);
  assert.match(proxy, /incoming\.pathname === "\/api\/auth\/demo-login"/);
});
