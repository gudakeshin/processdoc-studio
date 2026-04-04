import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";

const ROOT = path.resolve(process.cwd());

async function read(relPath) {
  return readFile(path.join(ROOT, relPath), "utf-8");
}

test("SSE stream listener includes output_chunk event", async () => {
  const content = await read("hooks/useRunStream.ts");
  assert.match(content, /"output_chunk"/);
});

test("admin skills page includes create and delete actions", async () => {
  const content = await read("app/admin/skills/page.tsx");
  assert.match(content, /Validate & Save/);
  assert.match(content, /deleteSkill/);
});

test("admin LP page includes search and bookmark actions", async () => {
  const content = await read("app/admin/lp-library/page.tsx");
  assert.match(content, /Refresh index/);
  assert.match(content, /Bookmark/);
});

test("auth context does not force JSON content-type for FormData", async () => {
  const content = await read("lib/auth-context.tsx");
  assert.match(content, /isFormData/);
  assert.match(content, /!isFormData/);
});

test("project route uses unified project studio container", async () => {
  const content = await read("app/projects/[pid]/page.tsx");
  assert.match(content, /ProjectStudioUnified/);
  assert.match(content, /searchParams\.get\("run"\)/);
});

test("run route reuses unified project studio container", async () => {
  const content = await read("app/projects/[pid]/runs/[rid]/page.tsx");
  assert.match(content, /ProjectStudioUnified/);
  assert.match(content, /initialRunId=\{rid\}/);
});
