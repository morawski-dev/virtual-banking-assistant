import logging
import os
from typing import Optional

from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from mock_cb.rag.loader import load_rag_content

logger = logging.getLogger(__name__)

COLLECTION_NAME = "rag_demo"
EMBED_DIM = 1536  # text-embedding-3-small output dimensions


def _make_qdrant_client() -> QdrantClient:
    qdrant_url = os.getenv("QDRANT_URL")
    if qdrant_url:
        logger.info("Qdrant client: remote (%s)", qdrant_url)
        return QdrantClient(url=qdrant_url, timeout=5)
    logger.info("Qdrant client: in-memory embedded")
    return QdrantClient(location=":memory:")


def build_index() -> Optional[VectorStoreIndex]:
    """Build LlamaIndex VectorStoreIndex backed by Qdrant.

    Returns None when OPENAI_API_KEY is missing or initialisation fails,
    so the caller can fall back to the RAG_CHUNKS stub.
    """
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY missing — RAG falls back to RAG_CHUNKS stub")
        return None
    try:
        embed_model = OpenAIEmbedding(model="text-embedding-3-small")
        Settings.embed_model = embed_model

        docs = load_rag_content()
        splitter = SentenceSplitter(chunk_size=256, chunk_overlap=32)
        nodes = splitter.get_nodes_from_documents(docs)

        client = _make_qdrant_client()
        # Recreate collection for a clean slate on every startup (ephemeral semantics).
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass  # collection didn't exist yet
        client.create_collection(
            COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )

        vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex(nodes, storage_context=storage_context)

        logger.info(
            "RAG index built: %d nodes from %d docs (collection=%s)",
            len(nodes),
            len(docs),
            COLLECTION_NAME,
        )

        # Sanity check: DoD requires the §3.1 chunk with 7% and kapitalizacja
        has_dod_chunk = any(
            "7%" in n.get_content() and "kapitalizacja" in n.get_content() for n in nodes
        )
        if not has_dod_chunk:
            logger.warning("DoD chunk missing: no node contains '7%%' and 'kapitalizacja'")

        return index
    except Exception:
        logger.exception("RAG index build failed")
        return None
