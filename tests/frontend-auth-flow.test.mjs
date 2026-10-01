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
