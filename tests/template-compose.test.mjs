import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("template composer submits product, template and user requirement to the AI backend", async () => {
  const source = await readFile(new URL("../app/ui/TemplateLab.tsx", import.meta.url), "utf8");
  assert.match(source, /form\.append\("product_images"/);
  assert.match(source, /form\.append\("template_image"/);
  assert.match(source, /confirmedSelection\.forEach\(\(item\) => form\.append\("template_image_ids", item\.id\)\)/);
  assert.doesNotMatch(source, /fetch\(item\.imageUrl\)/);
  assert.match(source, /if \(templateUpload\) \{\s*form\.append\("template_image", templateUpload\.file/);
  assert.match(source, /form\.append\("requirement"/);
  assert.match(source, /\/api\/template-compose\/generate/);
  assert.match(source, /上传自己的模板图/);
  assert.match(source, /new EventSource\(`\$\{API\}\/api\/ai\/connections\/stream`\)/);
  assert.match(source, /if \(!streamOpen\) void readStatus\(\)/);
});
