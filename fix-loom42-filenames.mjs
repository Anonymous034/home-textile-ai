import { readdir, rename, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const root = join(import.meta.dirname, 'public', 'template-library', 'images');
const decode = (text) => Buffer.from(text, 'latin1').toString('utf8');
const isBroken = (text) => /[åæçèé]/.test(text);
let renamedTemplates = 0;
let renamedCategories = 0;

for (const categoryName of await readdir(root)) {
  const categoryPath = join(root, categoryName);
  if (!isBroken(categoryName)) continue;

  for (const templateName of await readdir(categoryPath)) {
    if (!isBroken(templateName)) continue;
    await rename(join(categoryPath, templateName), join(categoryPath, decode(templateName)));
    renamedTemplates += 1;
  }

  await rename(categoryPath, join(root, decode(categoryName)));
  renamedCategories += 1;
}

const manifestPath = join(root, 'manifest.json');
const manifest = JSON.parse((await readFile(manifestPath, 'utf8')).replace(/^\uFEFF/, ''));
for (const item of manifest) {
  if (isBroken(item.category)) item.category = decode(item.category);
  if (isBroken(item.template)) item.template = decode(item.template);
}
await writeFile(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');

console.log(JSON.stringify({ renamedCategories, renamedTemplates, manifestRecords: manifest.length }));
