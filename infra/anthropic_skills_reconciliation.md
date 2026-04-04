# Anthropic skills reconciliation (mapped built-ins)

Reconciled eight ProcessDoc built-in skills to mirror [anthropics/skills](https://github.com/anthropics/skills/tree/main/skills) layout: `SKILL.md`, `LICENSE.txt` (where upstream provides it), `scripts/**`, and sibling reference markdown (`editing.md`, `pptxgenjs.md`, `forms.md`, `reference.md`).

## App skill → upstream folder

| App `id` | Upstream folder |
|----------|-----------------|
| `docx_v1` | `skills/docx` |
| `pptx_v1` | `skills/pptx` |
| `pdf_v1` | `skills/pdf` |
| `xlsx_v1` | `skills/xlsx` |
| `brand_guidelines_v1` | `skills/brand-guidelines` |
| `frontend_design_docx_v1` | `skills/frontend-design` |
| `frontend_design_pptx_v1` | `skills/frontend-design` |
| `frontend_design_xlsx_v1` | `skills/frontend-design` |

## File parity (local tree vs clone of `main`)

Counts of files under each directory (excluding `.git`):

| Scope | Files |
|-------|------:|
| `backend/config/skills/docx_v1` | 61 |
| upstream `skills/docx` | 61 |
| `backend/config/skills/pptx_v1` | 59 |
| upstream `skills/pptx` | 59 |
| `backend/config/skills/pdf_v1` | 12 |
| upstream `skills/pdf` | 12 |
| `backend/config/skills/xlsx_v1` | 54 |
| upstream `skills/xlsx` | 54 |
| `backend/config/skills/brand_guidelines_v1` | 2 |
| upstream `skills/brand-guidelines` | 2 |
| Each `frontend_design_*_v1` | 2 |
| upstream `skills/frontend-design` | 2 |

## Intentional differences

1. **`SKILL.md` frontmatter** — ProcessDoc YAML metadata (`id`, `domain`, `tools`, `companion_files`, etc.) is preserved from the pre-merge skill card. The **markdown body** after `---` is taken from the upstream Anthropic `SKILL.md` (replacing upstream’s `name` / `description` / `license` frontmatter keys).
2. **Companion allowlist** — `pptx_v1` and `pdf_v1` use paths relative to each skill directory (`./editing.md`, `./pptxgenjs.md`, `./forms.md`, `./reference.md`). [`backend/config/skill_registry.json`](../backend/config/skill_registry.json) lists the same files via repo-root paths for documentation consistency.
3. **Frontend-design variants** — Three app skills share one upstream folder; each directory is a full copy. Bodies are identical; **frontmatter** differs per `output_types` / display name. Previous per-format “CRITICAL OUTPUT CONTRACT” paragraphs in the body are superseded by the shared upstream body (exact-mirror choice).
4. **`brand_guidelines_v1`** — Instruction body now follows upstream `brand-guidelines`; ProcessDoc frontmatter still describes Deloitte-oriented styling where configured historically (review if you want body and metadata aligned).

## Repeat the sync

```bash
git clone --depth 1 https://github.com/anthropics/skills.git /tmp/anthropics-skills
cd /path/to/Process\ Doc\ v2
python3 backend/scripts/mirror_anthropic_skills.py /tmp/anthropics-skills/skills
```

Then re-apply any manual tweaks to frontmatter if upstream structure changes.

## Legacy companion path

[`backend/config/skill_companions/`](../backend/config/skill_companions/) no longer holds duplicate PPTX/PDF markdown; see `README.md` there.
