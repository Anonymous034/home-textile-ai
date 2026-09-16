import { readFile, writeFile, mkdir, rename, rm, stat } from 'node:fs/promises';
import { existsSync, statSync } from 'node:fs';
import { dirname, extname, join } from 'node:path';

const root = join(import.meta.dirname, 'public', 'template-library', 'images');
const records = JSON.parse((await readFile(join(root, 'manifest.json'), 'utf8')).replace(/^\uFEFF/, ''));
const safe = (value) => value.replace(/[\\/:*?"<>|]/g, '_');
const fileFor = (item) => join(root, safe(item.category), safe(item.template), `${String(item.slot + 1).padStart(2, '0')}${extname(new URL(item.url).pathname) || '.jpg'}`);
const queue = records.filter((item) => !existsSync(fileFor(item)) || statSync(fileFor(item)).size === 0);
let next = 0;
let complete = records.length - queue.length;
const failed = [];

async function download(item) {
  const destination = fileFor(item);
  const partial = `${destination}.part`;
  await mkdir(dirname(destination), { recursive: true });
  await rm(partial, { force: true });
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(item.url, { signal: AbortSignal.timeout(60000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await writeFile(partial, new Uint8Array(await response.arrayBuffer()));
      if ((await stat(partial)).size === 0) throw new Error('empty response');
      await rename(partial, destination);
      return;
    } catch (error) {
      await rm(partial, { force: true });
      if (attempt === 3) throw error;
    }
  }
}

async function worker() {
  while (next < queue.length) {
    const item = queue[next++];
    try { await download(item); } catch (error) { failed.push({ ...item, error: String(error) }); }
    complete += 1;
    if (complete % 25 === 0 || complete === records.length) console.log(`${complete}/${records.length}`);
  }
}

await Promise.all(Array.from({ length: 12 }, worker));
await writeFile(join(root, 'failed-downloads.json'), JSON.stringify(failed, null, 2));
console.log(`Finished ${complete}/${records.length}; failures: ${failed.length}`);
