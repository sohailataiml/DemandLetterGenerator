/**
 * Put the PDF.js worker where the browser can fetch it.
 *
 * The evidence viewer renders original PDFs in the browser, which means the
 * worker has to be served as a static asset rather than bundled. Copying it
 * from node_modules at build time keeps one version of pdfjs-dist in play —
 * a worker that drifts from the library it serves fails at runtime, not at
 * build time, which is the worst place to find out.
 */

import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const publicDir = join(here, "..", "public");

try {
  const pdfjs = dirname(require.resolve("pdfjs-dist/package.json"));
  const worker = join(pdfjs, "build", "pdf.worker.min.mjs");
  if (!existsSync(worker)) {
    console.warn(`[pdf-worker] not found at ${worker}; the evidence viewer will fall back`);
    process.exit(0);
  }
  mkdirSync(publicDir, { recursive: true });
  copyFileSync(worker, join(publicDir, "pdf.worker.min.mjs"));
  console.log("[pdf-worker] copied pdf.worker.min.mjs into public/");
} catch (error) {
  // Not fatal: without the worker the viewer shows extracted text instead of
  // the rendered page, which is a degraded view, not a broken build.
  console.warn(`[pdf-worker] skipped: ${error.message}`);
}
