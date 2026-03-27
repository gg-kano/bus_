"""
FAQ RAG (Retrieval Augmented Generation) system with embedding database.

Uses:
- Ollama with bge-m3 for embeddings (open-source, multilingual)
- ChromaDB for vector storage
"""

import json
import os
import logging
import httpx
from typing import List, Dict, Optional

import chromadb

logger = logging.getLogger(__name__)
from chromadb.config import Settings

# Config
FAQ_DIR = os.path.join(os.path.dirname(__file__), "faq")
CHROMA_PATH = os.getenv("CHROMA_PATH", "/tmp/chroma_faq")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")

# Collection name
FAQ_COLLECTION = "faq"


def load_faq() -> List[Dict]:
    """Load FAQ data from categorized folder structure.

    Structure:
        faq/
        ├── booking/
        │   ├── cancel.json
        │   └── change_seat.json
        ├── payment/
        │   └── methods.json
        └── travel/
            ├── what_to_bring.json
            └── missed_bus.json
    """
    faq_list = []
    faq_id = 1

    try:
        if not os.path.exists(FAQ_DIR):
            logger.warning(f"[RAG] FAQ directory not found: {FAQ_DIR}")
            return []

        # Walk through all subdirectories
        for category in sorted(os.listdir(FAQ_DIR)):
            category_path = os.path.join(FAQ_DIR, category)

            if not os.path.isdir(category_path):
                continue

            # Load all JSON files in this category
            for filename in sorted(os.listdir(category_path)):
                if not filename.endswith(".json"):
                    continue

                filepath = os.path.join(category_path, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        faq_data = json.load(f)
                        faq_data["id"] = faq_id
                        faq_data["category"] = category
                        faq_data["source"] = f"{category}/{filename}"
                        faq_list.append(faq_data)
                        faq_id += 1
                except Exception as e:
                    logger.error(f"[RAG] Failed to load {filepath}: {e}")

        logger.info(f"[RAG] Loaded {len(faq_list)} FAQs from {FAQ_DIR}")
        return faq_list

    except Exception as e:
        logger.error(f"[RAG] Failed to load FAQ: {e}")
        return []


def get_embedding(text: str) -> Optional[List[float]]:
    """Get embedding from Ollama (using bge-m3)."""
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={
                    "model": EMBEDDING_MODEL,
                    "prompt": text
                }
            )
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception as e:
        logger.error(f"[RAG] Embedding error: {e}")
        return None


class FAQVectorStore:
    """ChromaDB-based vector store for FAQ."""

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = None
        self._initialized = False

    def initialize(self):
        """Initialize the vector store with FAQ data."""
        if self._initialized:
            return

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=FAQ_COLLECTION,
            metadata={"description": "Bus booking FAQ"}
        )

        # Check if already populated
        if self.collection.count() > 0:
            logger.info(f"[RAG] FAQ collection already exists with {self.collection.count()} entries")
            self._initialized = True
            return

        # Load and embed FAQ
        faq_data = load_faq()
        if not faq_data:
            logger.warning("[RAG] No FAQ data to load")
            return

        logger.info(f"[RAG] Embedding {len(faq_data)} FAQ entries...")

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for faq in faq_data:
            # Combine question and keywords for better matching
            text_to_embed = f"{faq['question']} {' '.join(faq.get('keywords', []))}"
            embedding = get_embedding(text_to_embed)

            if embedding:
                ids.append(str(faq["id"]))
                embeddings.append(embedding)
                documents.append(faq["answer"])
                metadatas.append({
                    "question": faq["question"],
                    "keywords": ",".join(faq.get("keywords", [])),
                    "category": faq.get("category", ""),
                    "source": faq.get("source", "")
                })

        if embeddings:
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            logger.info(f"[RAG] Successfully added {len(embeddings)} FAQ entries to vector store")

        self._initialized = True

    def search(self, query: str, top_k: int = 2) -> List[Dict]:
        """Search for relevant FAQ entries."""
        if not self._initialized:
            self.initialize()

        if not self.collection or self.collection.count() == 0:
            return []

        # Get query embedding
        query_embedding = get_embedding(query)
        if not query_embedding:
            logger.warning("[RAG] Failed to get query embedding")
            return []

        # Search
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )

        # Format results
        faq_results = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0
                # ChromaDB returns L2 distance, lower is better
                # Convert to similarity score (0-1, higher is better)
                similarity = 1 / (1 + distance)

                # Only include if similarity is reasonable (threshold ~0.3)
                if similarity > 0.3:
                    faq_results.append({
                        "id": doc_id,
                        "question": results["metadatas"][0][i].get("question", ""),
                        "answer": results["documents"][0][i],
                        "similarity": similarity
                    })

        if faq_results:
            logger.info(f"[RAG] Query: '{query[:50]}...' -> Found {len(faq_results)} relevant FAQ(s)")
            for r in faq_results:
                logger.debug(f"[RAG]   - {r['question'][:40]}... (similarity: {r['similarity']:.2f})")

        return faq_results

    def reload(self):
        """Reload FAQ data (delete and re-add)."""
        if self.collection:
            self.client.delete_collection(FAQ_COLLECTION)
        self._initialized = False
        self.initialize()


# Global instance
_vector_store: Optional[FAQVectorStore] = None


def get_vector_store() -> FAQVectorStore:
    """Get or create the global vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = FAQVectorStore()
    return _vector_store


def retrieve_faq(query: str, top_k: int = 2) -> List[Dict]:
    """Retrieve relevant FAQ entries for a query."""
    store = get_vector_store()
    return store.search(query, top_k)


def format_faq_context(faq_results: List[Dict]) -> str:
    """Format FAQ results as context for the LLM."""
    if not faq_results:
        return ""

    lines = ["FAQ INFO (use these answers for policy questions):"]
    for i, faq in enumerate(faq_results, 1):
        lines.append(f"Q: {faq['question']}")
        lines.append(f"A: {faq['answer']}")
        lines.append("")

    return "\n".join(lines)


def get_faq_context(query: str) -> str:
    """
    Main function to get FAQ context for a user query.

    Args:
        query: User's message/question

    Returns:
        Formatted FAQ context string, or empty string if no relevant FAQ
    """
    results = retrieve_faq(query)
    return format_faq_context(results)


def init_faq_store():
    """Initialize the FAQ vector store (call on app startup)."""
    store = get_vector_store()
    store.initialize()


# For testing
if __name__ == "__main__":
    print("=== FAQ RAG Test ===\n")

    # Initialize
    init_faq_store()

    test_queries = [
        "How can I cancel my ticket?",
        "What payment methods do you accept?",
        "Can I change my seat?",
        "What time does the bus leave?",
        "I missed my bus, what do I do?",
    ]

    for q in test_queries:
        print(f"\nQuery: {q}")
        context = get_faq_context(q)
        if context:
            print(context)
        else:
            print("No relevant FAQ found.")
        print("-" * 50)
