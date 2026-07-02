"""LLM edit-format instructions (Aider diff vs new-file blocks)."""

from __future__ import annotations

NEW_FILE_BLOCK_INSTRUCTION = (
    "Respond ONLY with new-file blocks in this exact format:\n"
    "```file:backend/path/to/new_or_small_file.py\n"
    "<full file contents>\n"
    "```\n"
    "Use paths relative to the repository root. Place tests under `backend/tests/` never `backend/app/tests/`. "
    "Do not include secrets or .env files."
)

PATCH_BLOCK_INSTRUCTION = (
    "Respond ONLY with SEARCH/REPLACE edit blocks (Aider diff format). "
    "Never output a full large file — only the lines that change plus minimal surrounding context.\n\n"
    "Format (repeat per file/hunk):\n"
    "backend/path/to/file.py\n"
    "```python\n"
    "<<<<<<< SEARCH\n"
    "<exact lines copied from the file — must match character-for-character>\n"
    "=======\n"
    "<replacement lines>\n"
    ">>>>>>> REPLACE\n"
    "```\n\n"
    "Rules:\n"
    "- Include only 3–15 lines in each SEARCH section (enough to be unique).\n"
    "- Break large changes into multiple SEARCH/REPLACE blocks.\n"
    "- For a brand-new file, use an empty SEARCH section.\n"
    "- Do not use ```file:``` full-file blocks for paths over 500 lines.\n"
    "- Place tests under `backend/tests/`."
)

IMPLEMENT_FILE_BLOCK_INSTRUCTION = (
    "Use ```file:``` blocks for NEW files only. "
    "For EXISTING large files (routers, app.js, governance markdown), use SEARCH/REPLACE blocks only.\n"
    + PATCH_BLOCK_INSTRUCTION
)

GOVERNANCE_PATCH_BLOCK_INSTRUCTION = (
    "Respond ONLY with SEARCH/REPLACE edit blocks for governance markdown files.\n\n"
    "Format:\n"
    "### `backend/docs/governance/api-inventory-and-ui-map.md`\n"
    "```markdown\n"
    "<<<<<<< SEARCH\n"
    "| GET    | `/v1/vector_stores/{store_id}` | Partial | ... |\n"
    "=======\n"
    "| GET    | `/v1/vector_stores/{store_id}` | Full | ... |\n"
    ">>>>>>> REPLACE\n"
    "```\n\n"
    "Strict rules:\n"
    "- Patch ONLY governance markdown under `backend/docs/governance/` — never edit frontend files.\n"
    "- ONE table row per hunk; SEARCH is the exact row from context (5-12 lines max).\n"
    "- Never include `... [truncated]` or placeholder lines in SEARCH.\n"
)

UI_PATCH_BLOCK_INSTRUCTION = (
    "Respond ONLY with SEARCH/REPLACE edit blocks for UI or governance files.\n\n"
    "Format:\n"
    "frontend/views/routing-gateway.html\n"
    "```html\n"
    "<<<<<<< SEARCH\n"
    "<exact 5-15 consecutive lines copied verbatim from ONE anchor region in context>\n"
    "=======\n"
    "<replacement lines>\n"
    ">>>>>>> REPLACE\n"
    "```\n\n"
    "Strict rules:\n"
    "- ONE hunk per file; SEARCH must be 5-15 lines from a single anchor (tab button, form, or panel section).\n"
    "- Copy lines exactly from context — never include `... [truncated]`, `lines omitted`, or `...` placeholders.\n"
    "- For NEW UI sections, use append mode: SEARCH is the closing anchor line(s) "
    "(e.g. `</div>` before a sibling panel); REPLACE repeats SEARCH plus your new markup after it.\n"
    "- For governance markdown, patch only ONE table row (5-8 lines max in SEARCH).\n"
    "- Never output ```file:``` full-file rewrites of app.js or routing-gateway.html.\n"
    "- Prefer adding a small operator panel or wiring one handler — not refactoring large blocks.\n"
)
