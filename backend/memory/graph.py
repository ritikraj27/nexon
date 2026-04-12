# backend/memory/graph.py
# ============================================================
# NEXON Persistent Long-Term Memory Graph
# Stores facts, decisions, preferences, and events across ALL
# sessions. Supports semantic search via embeddings.
#
# Think of it as NEXON's permanent brain — not just chat logs.
#
# Usage:
#   memory = MemoryGraph(db)
#   memory.store("John's email is john@example.com", tags=["contact"])
#   results = memory.search("John's contact info", top_k=3)
# ============================================================

import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session as DBSession

from backend.memory.embeddings import embed, json_to_vec, vec_to_json, find_most_similar
from backend.db.models import MemoryNode, MemoryEdge


class MemoryGraph:
    """
    Persistent semantic memory graph for NEXON.

    Memory is stored as nodes (facts/events) with embeddings
    enabling fast semantic search. Edges connect related nodes.

    All memories persist in SQLite across ALL sessions and app restarts.

    Args:
        db : SQLAlchemy session.
    """

    def __init__(self, db: DBSession):
        self.db = db

    # ──────────────────────────────────────────
    # STORE
    # ──────────────────────────────────────────

    def store(
        self,
        content    : str,
        memory_type: str = "fact",      # fact | event | preference | decision | contact
        tags       : List[str] = None,
        session_id : Optional[int] = None,
        importance : float = 0.5,       # 0-1 scale
        source     : str = "user",      # user | agent | system
    ) -> "MemoryNode":
        """
        Store a new memory node with semantic embedding.

        Args:
            content     : The memory text (e.g., "John prefers morning meetings").
            memory_type : Category of memory.
            tags        : Optional list of tags for filtering.
            session_id  : Session this memory came from.
            importance  : How important to retain (0=low, 1=critical).
            source      : Who created this memory.
        Returns:
            Created MemoryNode ORM object.
        """
        # Generate embedding
        vec     = embed(content)
        vec_str = vec_to_json(vec)

        node = MemoryNode(
            content     = content,
            memory_type = memory_type,
            tags        = json.dumps(tags or []),
            session_id  = session_id,
            importance  = importance,
            source      = source,
            embedding   = vec_str,
            created_at  = datetime.utcnow(),
            last_accessed= datetime.utcnow(),
            access_count = 0,
        )
        self.db.add(node)
        self.db.commit()
        self.db.refresh(node)

        # Auto-link to similar existing memories
        self._create_similarity_edges(node, vec)

        return node

    def _create_similarity_edges(self, new_node: "MemoryNode", vec: List):
        """
        Create edges between new node and existing similar memories.
        This builds the graph structure for traversal.
        """
        existing = self.db.query(MemoryNode).filter(
            MemoryNode.id != new_node.id,
            MemoryNode.embedding != None
        ).limit(200).all()

        candidates = [
            (str(n.id), json_to_vec(n.embedding))
            for n in existing if n.embedding
        ]

        if not candidates:
            return

        similar = find_most_similar(vec, candidates, top_k=3, threshold=0.6)

        for node_id_str, score in similar:
            edge = MemoryEdge(
                from_node_id = new_node.id,
                to_node_id   = int(node_id_str),
                weight       = score,
                edge_type    = "similar",
                created_at   = datetime.utcnow(),
            )
            self.db.add(edge)

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

    # ──────────────────────────────────────────
    # SEARCH
    # ──────────────────────────────────────────

    def search(
        self,
        query    : str,
        top_k    : int = 5,
        memory_type: Optional[str] = None,
        tags     : Optional[List[str]] = None,
        min_importance: float = 0.0,
        days_back: Optional[int] = None,
    ) -> List[Dict]:
        """
        Semantic search over all stored memories.

        Args:
            query         : Natural language search query.
            top_k         : Max results to return.
            memory_type   : Filter by memory type.
            tags          : Filter by tags (any match).
            min_importance: Minimum importance threshold.
            days_back     : Only search memories from last N days.
        Returns:
            List of dicts with keys: id, content, type, tags, score, created_at.
        """
        query_vec = embed(query)

        # Build DB query
        q = self.db.query(MemoryNode).filter(
            MemoryNode.embedding != None,
            MemoryNode.importance >= min_importance,
        )

        if memory_type:
            q = q.filter(MemoryNode.memory_type == memory_type)

        if days_back:
            cutoff = datetime.utcnow() - timedelta(days=days_back)
            q = q.filter(MemoryNode.created_at >= cutoff)

        nodes = q.all()

        if not nodes:
            return []

        # Score by similarity
        candidates = [
            (str(n.id), json_to_vec(n.embedding))
            for n in nodes if n.embedding
        ]

        similar = find_most_similar(query_vec, candidates, top_k=top_k * 2, threshold=0.2)
        id_score = {int(s[0]): s[1] for s in similar}

        results = []
        node_map = {n.id: n for n in nodes}

        for node_id, score in sorted(id_score.items(), key=lambda x: -x[1])[:top_k]:
            node = node_map.get(node_id)
            if not node:
                continue

            # Boost score by importance and recency
            days_old = (datetime.utcnow() - node.created_at).days
            recency_boost = max(0, 1 - days_old / 365) * 0.1
            final_score   = score + node.importance * 0.15 + recency_boost

            # Update access stats
            node.access_count = (node.access_count or 0) + 1
            node.last_accessed = datetime.utcnow()

            results.append({
                "id"        : node.id,
                "content"   : node.content,
                "type"      : node.memory_type,
                "tags"      : json.loads(node.tags or "[]"),
                "score"     : round(final_score, 3),
                "importance": node.importance,
                "source"    : node.source,
                "created_at": node.created_at.isoformat(),
                "session_id": node.session_id,
            })

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

        return sorted(results, key=lambda x: -x["score"])

    # ──────────────────────────────────────────
    # EXTRACT & AUTO-STORE
    # ──────────────────────────────────────────

    async def extract_and_store(
        self,
        user_text   : str,
        ai_response : str,
        session_id  : int,
        emotion     : str = "neutral",
    ) -> List[Dict]:
        """
        Auto-extract memorable facts from a conversation turn
        and store them in the memory graph.

        Extracts: contacts, preferences, decisions, facts, events.
        Triggered automatically after every /chat response.

        Args:
            user_text   : What the user said.
            ai_response : What NEXON replied.
            session_id  : Active session.
            emotion     : User emotion at time of exchange.
        Returns:
            List of stored memory summaries.
        """
        from backend.llm_engine import nexon_llm

        extraction_prompt = f"""
Analyze this conversation exchange and extract any facts worth remembering long-term.
Return ONLY a JSON array. Each item: {{"content": "...", "type": "fact|preference|decision|contact|event", "importance": 0.0-1.0, "tags": []}}
If nothing worth remembering, return [].

User said: {user_text}
NEXON replied: {ai_response[:300]}

Extract facts like: names, emails, preferences, decisions made, important events, goals, deadlines.
Return raw JSON only, no markdown.
"""
        try:
            raw = await nexon_llm.generate_response(
                extraction_prompt,
                language="en",
                max_tokens=400,
            )
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            facts = json.loads(raw)
            if not isinstance(facts, list):
                return []
        except Exception:
            return []

        stored = []
        for fact in facts[:5]:  # Max 5 memories per turn
            content    = fact.get("content", "").strip()
            mem_type   = fact.get("type", "fact")
            importance = float(fact.get("importance", 0.5))
            tags       = fact.get("tags", [])

            if not content or len(content) < 10:
                continue

            # Don't store duplicates (check similarity)
            existing = self.search(content, top_k=1, min_importance=0.0)
            if existing and existing[0]["score"] > 0.85:
                continue  # Already know this

            node = self.store(
                content    = content,
                memory_type= mem_type,
                tags       = tags + ([emotion] if emotion != "neutral" else []),
                session_id = session_id,
                importance = importance,
                source     = "auto",
            )
            stored.append({"id": node.id, "content": content, "type": mem_type})

        return stored

    # ──────────────────────────────────────────
    # QUERY HELPERS
    # ──────────────────────────────────────────

    def get_context_for_prompt(self, query: str, max_memories: int = 5) -> str:
        """
        Retrieve relevant memories and format them as context
        to prepend to an LLM prompt.

        Args:
            query       : Current user query.
            max_memories: How many memories to include.
        Returns:
            Formatted string with relevant memories, or empty string.
        """
        memories = self.search(query, top_k=max_memories, min_importance=0.2)
        if not memories:
            return ""

        lines = ["[Relevant memories from previous sessions:"]
        for m in memories:
            lines.append(f"  • ({m['type']}) {m['content']}")
        lines.append("]")
        return "\n".join(lines)

    def get_all(
        self,
        memory_type: Optional[str] = None,
        limit      : int = 50,
        offset     : int = 0,
    ) -> List[Dict]:
        """Get all memories, optionally filtered by type."""
        q = self.db.query(MemoryNode)
        if memory_type:
            q = q.filter(MemoryNode.memory_type == memory_type)
        nodes = q.order_by(MemoryNode.created_at.desc()).offset(offset).limit(limit).all()
        return [
            {
                "id"        : n.id,
                "content"   : n.content,
                "type"      : n.memory_type,
                "tags"      : json.loads(n.tags or "[]"),
                "importance": n.importance,
                "source"    : n.source,
                "created_at": n.created_at.isoformat(),
                "access_count": n.access_count,
            }
            for n in nodes
        ]

    def delete(self, memory_id: int) -> bool:
        """Delete a memory node and its edges."""
        node = self.db.query(MemoryNode).filter(MemoryNode.id == memory_id).first()
        if node:
            self.db.delete(node)
            self.db.commit()
            return True
        return False

    def update_importance(self, memory_id: int, importance: float):
        """Adjust importance of a memory (e.g., user marked it as important)."""
        node = self.db.query(MemoryNode).filter(MemoryNode.id == memory_id).first()
        if node:
            node.importance = max(0.0, min(1.0, importance))
            self.db.commit()

    def get_stats(self) -> Dict:
        """Return memory graph statistics."""
        total  = self.db.query(MemoryNode).count()
        by_type= {}
        for t in ["fact", "preference", "decision", "contact", "event"]:
            by_type[t] = self.db.query(MemoryNode).filter(MemoryNode.memory_type == t).count()
        edges  = self.db.query(MemoryEdge).count()
        return {"total_nodes": total, "by_type": by_type, "total_edges": edges}