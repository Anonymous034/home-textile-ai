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

test("login form requests and verifies six-digit SMS codes", async () => {
  const form = await readFile(new URL("../app/ui/DemoLoginForm.tsx", import.meta.url), "utf8");
  assert.match(form, /fetch\("\/api\/auth\/request-code"/);
  assert.match(form, /fetch\("\/api\/auth\/verify-code"/);
  assert.match(form, /pattern="\[0-9\]\{6\}"/);
  assert.doesNotMatch(form, /DEMO_LOGIN_HINT|\/api\/auth\/demo-login/);
});

test("authentication calls use the frontend origin and a server-side proxy", async () => {
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
  assert.doesNotMatch(proxy, /DEMO_LOGIN_PUBLIC_ENABLED|demo-login/);
});
