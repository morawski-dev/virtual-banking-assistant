import logging
from typing import TYPE_CHECKING

from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

from mock_cb.models import RagChunk

if TYPE_CHECKING:
    from llama_index.core import VectorStoreIndex

logger = logging.getLogger(__name__)


def search(index: "VectorStoreIndex", doc: str, query: str) -> list[RagChunk]:
    """Retrieve top-k chunks from the Qdrant index, filtered by document name."""
    if not query:
        query = doc  # empty string has no meaningful embedding
    filters = MetadataFilters(filters=[MetadataFilter(key="doc", value=doc)])
    retriever = index.as_retriever(similarity_top_k=3, filters=filters)
    nodes = retriever.retrieve(query)
    if not nodes:
        return []
    chunks = []
    for node_with_score in nodes:
        node = node_with_score.node
        meta = node.metadata
        source = f"{meta.get('doc_title', doc)}, {meta.get('section', '')}".strip(", ")
        chunks.append(
            RagChunk(
                chunk_id=meta.get("chunk_id", "unknown"),
                text=node.get_content(),
                source=source,
            )
        )
    logger.info(
        "rag_search via llamaindex+qdrant: doc=%s query=%r chunks=%d", doc, query, len(chunks)
    )
    return chunks
