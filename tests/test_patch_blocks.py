from __future__ import annotations

from gateway_enhancement_agent.file_blocks import apply_llm_edits, preview_llm_edits
from gateway_enhancement_agent.patch_blocks import (
    apply_hunk_to_content,
    extract_search_replace_hunks,
    find_hunk_location,
    scoped_file_snippet,
    ui_scoped_snippet,
)
from gateway_enhancement_agent.route_modules import router_module_for_route


def test_extract_markdown_header_patch() -> None:
    text = """### `backend/docs/governance/api-inventory-and-ui-map.md`
```markdown
<<<<<<< SEARCH
| GET | `/v1/vector_stores` | Partial |
=======
| GET | `/v1/vector_stores` | Full |
>>>>>>> REPLACE
```"""
    hunks = extract_search_replace_hunks(text)
    assert len(hunks) == 1
    assert hunks[0].path.endswith("api-inventory-and-ui-map.md")
    assert "Partial" in hunks[0].search


def test_rejects_truncated_search_hunks() -> None:
    text = """backend/app/routers/gateway_rag.py
```python
<<<<<<< SEARCH
line one
... [truncated]
=======
line one
replaced
>>>>>>> REPLACE
```"""
    assert extract_search_replace_hunks(text) == []


def test_governance_inventory_row_patch_applies(tmp_path) -> None:
    rel = "backend/docs/governance/api-inventory-and-ui-map.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(
        "| GET    | `/v1/vector_stores`                | Partial     | notes |\n",
        encoding="utf-8",
    )
    text = f"""### `{rel}`
```html
<<<<<<< SEARCH
| GET    | `/v1/vector_stores`                                                 | Partial     | notes |
=======
| GET    | `/v1/vector_stores`                                                 | Full        | notes |
>>>>>>> REPLACE
```"""
    preview = preview_llm_edits(tmp_path, text)
    assert rel in preview
    assert "| Full        |" in preview[rel] or "| Full |" in preview[rel]


def test_extract_patch_fence() -> None:
    text = """```patch:backend/app/routers/gateway_rag.py
<<<<<<< SEARCH
def old():
    pass
=======
def new():
    pass
>>>>>>> REPLACE
```"""
    hunks = extract_search_replace_hunks(text)
    assert len(hunks) == 1
    assert hunks[0].path == "backend/app/routers/gateway_rag.py"
    assert "def old" in hunks[0].search


def test_apply_hunk_exact_match() -> None:
    original = "alpha\nbeta\ngamma\n"
    new, err = apply_hunk_to_content(original, "beta\n", "beta_patched\n")
    assert err is None
    assert new == "alpha\nbeta_patched\ngamma\n"


def test_apply_hunk_new_file() -> None:
    new, err = apply_hunk_to_content("", "", "hello\n")
    assert err is None
    assert new == "hello\n"


def test_find_hunk_location_fuzzy_whitespace() -> None:
    content = "def foo():\n    return 1\n"
    search = "def foo():\n\treturn 1\n"
    assert find_hunk_location(content, search) == 0


def test_scoped_snippet_around_anchor() -> None:
    content = "\n".join(f"line {i}" for i in range(200))
    content += '\n@router.get("/v1/vector_stores")\ndef handler():\n    return 1\n'
    snippet = scoped_file_snippet(content, anchors=['"/v1/vector_stores"'], context_lines=10, max_chars=5000)
    assert "/v1/vector_stores" in snippet
    assert "line 0" not in snippet


def test_ui_scoped_snippet_single_anchor_window() -> None:
    lines = [f"noise {i}" for i in range(100)]
    lines[50] = "function loadGatewayVectorStoreContext(storeId) {"
    lines[51] = "  return api(`/gateway/vector-stores/${storeId}/context`);"
    lines[52] = "}"
    content = "\n".join(lines)
    snippet = ui_scoped_snippet(content, anchors=["loadGatewayVectorStoreContext"], max_chars=1500)
    assert "loadGatewayVectorStoreContext" in snippet
    assert "noise 0" not in snippet
    assert "noise 99" not in snippet
    assert len(snippet) < 1600


def test_rejects_oversized_ui_search_hunk() -> None:
    search_lines = "\n".join(f"line {i}" for i in range(20))
    text = f"""frontend/app.js
```javascript
<<<<<<< SEARCH
{search_lines}
=======
{search_lines}
replaced
>>>>>>> REPLACE
```"""
    assert extract_search_replace_hunks(text) == []


def test_accepts_short_ui_append_hunk() -> None:
    text = """frontend/views/routing-gateway.html
```html
<<<<<<< SEARCH
<button id="testGatewayVectorStoreHealth" type="button" class="ghost">Test Selected Store</button>
=======
<button id="testGatewayVectorStoreHealth" type="button" class="ghost">Test Selected Store</button>
<button id="loadOpenAiVectorStoreDetail" type="button" class="ghost">Load OpenAI Store</button>
>>>>>>> REPLACE
```"""
    hunks = extract_search_replace_hunks(text)
    assert len(hunks) == 1
    assert "loadOpenAiVectorStoreDetail" in hunks[0].replace


def test_router_module_for_vector_stores() -> None:
    assert router_module_for_route("GET /v1/vector_stores") == "backend/app/routers/gateway_rag.py"
    assert router_module_for_route("POST /v1/vector_stores") == "backend/app/routers/gateway_rag.py"


def test_apply_llm_edits_rejects_full_gateway_overwrite(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "full")
    gateway = tmp_path / "backend/app/routers/gateway.py"
    gateway.parent.mkdir(parents=True)
    gateway.write_text("x = 1\n" * 600, encoding="utf-8")
    text = "```file:backend/app/routers/gateway.py\nreplacement\n```"
    result = apply_llm_edits(tmp_path, text, allowed_prefixes=["backend/"])
    assert "backend/app/routers/gateway.py" not in result.written
    assert any("rejected" in e.lower() or "forbidden" in e.lower() for e in result.errors)


def test_preview_llm_edits_applies_patch(tmp_path) -> None:
    rel = "backend/app/routers/gateway_rag.py"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("def before():\n    return 0\n", encoding="utf-8")
    text = f"""```patch:{rel}
<<<<<<< SEARCH
def before():
    return 0
=======
def before():
    return 1
>>>>>>> REPLACE
```"""
    preview = preview_llm_edits(tmp_path, text)
    assert preview[rel].strip().endswith("return 1")
