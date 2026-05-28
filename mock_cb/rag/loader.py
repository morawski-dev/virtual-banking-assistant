import re
from pathlib import Path

from llama_index.core import Document

CONTENT_DIR = Path(__file__).parent.parent / "rag_content"

DOC_META: dict[str, dict] = {
    "regulamin_konta_lokacyjnego.md": {
        "doc": "regulamin_konta_lokacyjnego.pdf",
        "doc_title": "Regulamin konta lokacyjnego Bank Demo",
        "id_prefix": "rkl",
    },
    "regulamin_konta_marzen.md": {
        "doc": "konto_marzen.pdf",  # matches bot function call and stub key
        "doc_title": "Oferta Konto Marzeń",
        "id_prefix": "rkm",
    },
    "tabela_oplat.md": {
        "doc": "tabela_oplat.pdf",
        "doc_title": "Tabela Opłat i Prowizji — Karta debetowa Premium 60+",
        "id_prefix": "top",
    },
}

# Matches ## par.X.X or ## str.X at start of line (ASCII-safe identifiers only)
_SECTION_RE = re.compile(r"^##\s+((?:par|str)\.\S+)", re.MULTILINE)


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Return list of (section_id, full_section_text) pairs."""
    sections: list[tuple[str, str]] = []
    current_section: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            if current_section is not None and current_lines:
                sections.append((current_section, "\n".join(current_lines).strip()))
            current_section = m.group(1)
            current_lines = [line]
        elif current_section is not None:
            current_lines.append(line)
    if current_section is not None and current_lines:
        sections.append((current_section, "\n".join(current_lines).strip()))
    return sections


def load_rag_content() -> list[Document]:
    """Parse markdown source files, return one Document per section."""
    documents: list[Document] = []
    for filename, meta in DOC_META.items():
        path = CONTENT_DIR / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for idx, (section_id, body) in enumerate(_parse_sections(text)):
            chunk_id = f"{meta['id_prefix']}-{idx + 1:03d}"
            documents.append(
                Document(
                    text=body,
                    metadata={
                        "doc": meta["doc"],
                        "doc_title": meta["doc_title"],
                        "section": section_id,
                        "chunk_id": chunk_id,
                    },
                )
            )
    return documents
