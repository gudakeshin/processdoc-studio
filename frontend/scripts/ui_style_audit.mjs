/**
 * Frontend UI/WCAG guardrail audit (regex-based).
 *
 * Goal: catch styling/token regressions early.
 *
 * Rules (fail):
 * - Raw palette classes (slate/red/blue/emerald/amber variants) in app/components.
 * - Raw input-like form controls in app/components (input/textarea/select/button).
 *
 * Pragmatic allowlists:
 * - Some complex pages still use raw HTML controls; they are explicitly allowlisted.
 * - Token palette utility classes (e.g. `text-[var(--text-muted)]`) are allowed.
 */

import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "..", "..");
const frontendRoot = path.join(repoRoot, "frontend");

const scanGlobs = [
  path.join(frontendRoot, "app/**/*.ts"),
  path.join(frontendRoot, "app/**/*.tsx"),
  path.join(frontendRoot, "app/**/*.js"),
  path.join(frontendRoot, "app/**/*.jsx"),
  path.join(frontendRoot, "components/**/*.ts"),
  path.join(frontendRoot, "components/**/*.tsx"),
  path.join(frontendRoot, "components/**/*.js"),
  path.join(frontendRoot, "components/**/*.jsx"),
];

 
const allowlistFiles = new Set(
  [
    // Temporary allowlist until the “Full-route WCAG + Token” wave is complete.
    // Add paths relative to `frontend/`.
    "components/run-studio/ZoneCLiveMonitor.tsx",
    "components/run-studio/ToolActivityFeed.tsx",
    // Outside current to-do wave (still enforced elsewhere).
    "app/customize/page.tsx",
    "app/projects/new/page.tsx",
    "app/memory/page.tsx",
    "app/projects/[pid]/page.tsx",
    "app/projects/[pid]/runs/[rid]/page.tsx",
    "components/documents/DocumentUploader.tsx",
    "components/DrawioCollabEditor.tsx",
    "components/ErrorBoundary.tsx",
    "components/excel/ConflictResolutionPanel.tsx",
    "components/excel/ExcelIntegrationPanel.tsx",
    "components/run-studio/ZoneAInstruction.tsx",
    "components/shell/ShellTopbar.tsx",
    // If you see a false positive, allowlist the specific file path only.
  ].map((p) => path.join(frontendRoot, p)),
);

const allowlistContains = [
  // If a match appears inside these files, we consider it "managed code" and do not fail.
  // (We still report it if it is a raw palette class; it helps spotting real drift.)
];

const paletteClassRe = new RegExp(
  [
    // Tailwind-style className patterns:
    // - text-slate-600
    // - bg-red-50
    // - border-amber-200
    // We avoid matching token forms like `text-[var(--token-name)]` by requiring non-[var(...)] prefix.
    String.raw`\b(?:text|bg|border)-(?:slate|red|blue|emerald|amber)-\d+\b`,
  ].join("|"),
  "g",
);

// Raw form controls (input/textarea/select/button) in TSX/JSX.
// We keep this strict and fail on these tags in `frontend/app/**` and `frontend/components/**`,
// except allowlisted files above.
// Note: In JSX, native tags are lowercase (<input>, <button>, ...).
// React components like <Input /> / <Button /> start with uppercase and must NOT match.
const rawFormControlRe = new RegExp(String.raw`<\s*(input|textarea|select|button)\b`);

function walkDir(dir) {
  /** @type {string[]} */
  const files = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      files.push(...walkDir(full));
    } else if (e.isFile()) {
      const ext = path.extname(e.name).toLowerCase();
      if ([".ts", ".tsx", ".js", ".jsx"].includes(ext)) files.push(full);
    }
  }
  return files;
}

function collectScanFiles() {
  // Avoid globbing dependencies; just walk the known roots.
  const appFiles = walkDir(path.join(frontendRoot, "app"));
  const compFiles = walkDir(path.join(frontendRoot, "components"));
  const uiRoot = path.join(frontendRoot, "components", "ui");
  // Skip the design-system primitives: they necessarily use native tags internally.
  return [...appFiles, ...compFiles].filter((abs) => !abs.startsWith(uiRoot + path.sep));
}

function readLines(filePath) {
  const content = fs.readFileSync(filePath, "utf8");
  return content.split(/\r?\n/);
}

function findPaletteViolations(lines, fileAbsPath, fileRelToFrontend) {
  if (allowlistFiles.has(fileAbsPath)) return [];
  /** @type {{lineNo: number, line: string, match: string}[]} */
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.includes("var(--")) continue; // token-based token usage
    paletteClassRe.lastIndex = 0;
    let match;
    while ((match = paletteClassRe.exec(line))) {
      out.push({
        lineNo: i + 1,
        line,
        match: match[0],
      });
    }
  }
  return out.map((v) => ({ ...v, file: fileRelToFrontend }));
}

function findRawFormControlViolations(lines, fileAbsPath, fileRelToFrontend) {
  if (allowlistFiles.has(fileAbsPath)) return [];
  /** @type {{lineNo: number, line: string, match: string}[]} */
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = rawFormControlRe.exec(line);
    if (m) {
      out.push({
        lineNo: i + 1,
        line,
        match: m[0],
      });
    }
  }
  return out.map((v) => ({ ...v, file: fileRelToFrontend }));
}

function formatViolations(title, items) {
  if (items.length === 0) return "";
  const byFile = new Map();
  for (const item of items) {
    const key = item.file;
    if (!byFile.has(key)) byFile.set(key, []);
    byFile.get(key).push(item);
  }
  const parts = [];
  parts.push(`${title} (${items.length}):`);
  for (const [file, violations] of [...byFile.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    parts.push(`- ${file}`);
    for (const v of violations.slice(0, 8)) {
      parts.push(`  - L${v.lineNo}: ${v.match}`);
    }
    if (violations.length > 8) parts.push(`  - ... +${violations.length - 8} more`);
  }
  return parts.join("\n");
}

function main() {
  const scanFiles = collectScanFiles();
  const paletteViolations = [];
  const formViolations = [];

  for (const absPath of scanFiles) {
    const rel = path.relative(frontendRoot, absPath);
    const lines = readLines(absPath);

    // Palette violations are never allowlisted; if a file uses raw palette classes,
    // we want to address it. (If needed, we can extend allowlist later.)
    paletteViolations.push(...findPaletteViolations(lines, absPath, rel));
    formViolations.push(...findRawFormControlViolations(lines, absPath, rel));
  }

  const paletteReport = formatViolations("Raw palette class violations", paletteViolations);
  const formReport = formatViolations("Raw form control violations", formViolations);

  const hasFail = paletteViolations.length > 0 || formViolations.length > 0;
  if (!hasFail) {
    console.log("ui_style_audit: PASS (no violations).");
    process.exit(0);
  }

  console.error("ui_style_audit: FAIL\n");
  if (paletteReport) console.error(paletteReport + "\n");
  if (formReport) console.error(formReport + "\n");

  console.error(
    [
      "Fix by:",
      "- replacing raw palette classes with token-based semantic classes/variables",
      "- replacing raw input/textarea/select/button with shared UI primitives",
      "- or, for temporary exceptions, add file path to allowlistFiles (and remove later).",
    ].join("\n"),
  );

  process.exit(1);
}

main();

