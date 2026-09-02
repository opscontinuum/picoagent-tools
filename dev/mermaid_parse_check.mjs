// Validate every ```mermaid block in a set of markdown files against Mermaid's own parser.
//
// Deliberately small and readable: this file is the thing a reviewer has to trust, so it does
// exactly one job with no surprises. It reads files, calls mermaid.parse(), prints a verdict,
// and exits non-zero if anything failed.
//
// It does NOT install anything, reach the network, or write any file. The mermaid and jsdom
// packages must already exist in the directory passed as --modules; if they don't, this exits
// with a message rather than fetching them.
//
//   node dev/mermaid_parse_check.mjs --modules <dir-with-node_modules> <file-or-dir>...
//
// Note for anyone modifying this: do not add a static `import` of dompurify. Static imports
// evaluate before the body runs, so dompurify would initialise without a window and mermaid
// would reuse that broken module - producing confident false failures on every diagram.

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const modulesIndex = args.indexOf('--modules');
if (modulesIndex === -1 || !args[modulesIndex + 1]) {
  console.error('usage: node mermaid_parse_check.mjs --modules <dir> <file-or-dir>...');
  process.exit(2);
}
const modulesDir = resolve(args[modulesIndex + 1]);
const targets = args.filter((_, i) => i !== modulesIndex && i !== modulesIndex + 1);

for (const pkg of ['mermaid', 'jsdom']) {
  if (!existsSync(join(modulesDir, 'node_modules', pkg))) {
    console.error(`missing ${pkg} in ${modulesDir}/node_modules - install it yourself; ` +
                  `this script does not install anything`);
    process.exit(2);
  }
}

const { JSDOM } = await import(pathToFileURL(join(modulesDir, 'node_modules/jsdom/lib/api.js')).href);
const dom = new JSDOM('<!DOCTYPE html><body></body>', { pretendToBeVisual: true });
global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;

const mermaidUrl = pathToFileURL(join(modulesDir, 'node_modules/mermaid/dist/mermaid.core.mjs')).href;
const mermaid = (await import(mermaidUrl)).default;
mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });

function markdownFiles(target, out = []) {
  const stats = statSync(target);
  if (stats.isDirectory()) {
    for (const entry of readdirSync(target)) markdownFiles(join(target, entry), out);
  } else if (target.endsWith('.md')) {
    out.push(target);
  }
  return out;
}

const FENCE = /```mermaid\n([\s\S]*?)```/g;
let total = 0, failed = 0;

for (const target of targets) {
  for (const file of markdownFiles(target).sort()) {
    const text = readFileSync(file, 'utf8');
    let match, index = 0;
    while ((match = FENCE.exec(text)) !== null) {
      index++; total++;
      const firstLine = match[1].trim().split('\n')[0].slice(0, 40);
      try {
        await mermaid.parse(match[1]);
      } catch (err) {
        failed++;
        console.log(`FAIL ${file} #${index} (${firstLine})`);
        console.log(`     ${String(err.message).split('\n').slice(0, 3).join('\n     ')}`);
      }
    }
  }
}

console.log(`${total} diagram(s) parsed, ${failed} failed`);
process.exit(failed ? 1 : 0);
