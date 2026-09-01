#!/usr/bin/env python3
"""
BMO Semantic Memory — free-form conversational recall via local embeddings.

Unlike BMOMemory (fixed-schema facts: name/age/likes/job/...) and
JournalManager (nightly mood check-ins), this captures arbitrary things said
in conversation and lets BMO answer "what did I say about X" by semantic
similarity, not just exact keyword or regex match.

Uses Ollama's local embedding models — already part of this project's
Groq+Ollama stack, so no new dependency — and works fully offline. If Ollama
or the embedding model isn't available, recall degrades to plain keyword
overlap instead of failing outright.
"""
import os
import json
import math
import time
import threading

from bmo.paths import DATA_DIR, SEMANTIC_MEMORY_FILE as STORE_FILE

MAX_MEMORIES = 300

try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False


def _load():
    try:
        with open(STORE_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STORE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SemanticMemory:
    def __init__(self, embed_model="all-minilm", enabled=True, relevance_threshold=0.35):
        self.embed_model  = embed_model
        self.threshold    = relevance_threshold
        self.enabled      = enabled and HAS_OLLAMA
        self._memories    = _load()
        self._lock        = threading.Lock()
        self._warned      = False

        if enabled and not HAS_OLLAMA:
            print("[SEMEM] 'ollama' package not installed — recall will use "
                  "plain keyword matching instead of semantic search.", flush=True)
        else:
            print(f"[SEMEM] Ready. {len(self._memories)} stored memories "
                  f"(model={embed_model}).", flush=True)

    def _embed(self, text):
        if not self.enabled:
            return None
        try:
            resp = ollama.embed(model=self.embed_model, input=text)
            return list(resp.embeddings[0])
        except Exception as e:
            if not self._warned:
                print(f"[SEMEM] Embedding unavailable ({e}) — falling back to "
                      f"keyword search. Run: ollama pull {self.embed_model}", flush=True)
                self._warned = True
            return None

    def remember(self, text, source="chat"):
        """Store a memory. Computes the embedding synchronously — use
        remember_async() from latency-sensitive call sites."""
        text = text.strip()
        if len(text) < 8:
            return
        entry = {"text": text, "source": source, "ts": time.time(),
                 "embedding": self._embed(text)}
        with self._lock:
            self._memories.append(entry)
            self._memories = self._memories[-MAX_MEMORIES:]
            _save(self._memories)

    def remember_async(self, text, source="chat"):
        threading.Thread(target=self.remember, args=(text, source), daemon=True).start()

    def recall(self, query, top_k=5):
        """Most relevant stored memory texts for `query`, best first. Falls
        back to keyword overlap if embeddings aren't available."""
        with self._lock:
            memories = list(self._memories)
        if not memories:
            return []

        q_emb = self._embed(query)
        if q_emb is not None:
            scored = [(_cosine(q_emb, m["embedding"]), m) for m in memories if m.get("embedding")]
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                return [m["text"] for score, m in scored[:top_k] if score >= self.threshold]

        q_words = set(query.lower().split())
        scored = [(len(q_words & set(m["text"].lower().split())), m) for m in memories]
        scored = [(s, m) for s, m in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m["text"] for _, m in scored[:top_k]]

    def forget_all(self):
        with self._lock:
            self._memories = []
            _save(self._memories)
