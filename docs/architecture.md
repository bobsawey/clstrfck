# Living Knowledge Graph: Minimal Viable Architecture

```
    ┌──────────────┐         ┌───────────────┐        ┌─────────────┐
    │  Raw Sources │───────▶ │ Ingest/Extract│ ─────▶ │ Blob Store  │
    │ (FS/Web/API) │         │ (Python ETL)  │        │ (Object/ZST)│
    └──────────────┘         └──────┬────────┘        └─────┬───────┘
                                     │                          │
                                     ▼                          │
                            ┌─────────────┐                     │
                            │ Normalizer  │                     │
                            │  (ETL)      │                     │
                            └────┬────────┘                     │
                                 │                              │
                                 ▼                              │
         ┌─────────────────────────────────────────────────────────────┐
         │                   Content-Addressed Lake                    │
         │ ┌─────────────┐ ┌──────────────┐ ┌──────────────┐           │
         │ │  sources    │ │   blobs      │ │ extractions  │           │
         │ └────┬────────┘ └─────┬────────┘ └─────┬────────┘           │
         │      │                │                │                    │
         └──────┴────────────────┴────────────────┴────────────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────────────┐
                │           Chunker/Embedder             │
                │   (chunk into windows, make vectors)   │
                └───────────────┬────────────────────────┘
                                │
                                ▼
              ┌───────────────────────────────────┐
              │   Hot Set Parquet Tables          │
              │  (docs, chunks, embeddings)       │
              └───────────────┬───────────────────┘
                              │
                              ▼
           ┌─────────────────────────────────────────────────┐
           │      Graph Ingest & Enrichment (Python)         │
           │  - Upsert Docs, Chunks, Entities to Neo4j       │
           │  - Build SIMILAR_TO edges via GDS kNN           │
           │  - Compute density, etc.                        │
           └──────────────────┬──────────────────────────────┘
                              │
                              ▼
           ┌──────────────────────────────────┐
           │    Neo4j Graph Core + GDS        │
           │  - Nodes: Doc, Chunk, Entity     │
           │  - Edges: HAS_CHUNK, SIMILAR_TO, │
           │    MENTIONS, PRODUCED, etc.      │
           │  - Vector index (for seed search)│
           │  - Personalized PageRank (expand)│
           │  - All provenance logged         │
           └──────────────────┬───────────────┘
                              │
                              ▼
           ┌──────────────────────────────────┐
           │     Search & Synthesis API       │
           │  - Vector seeds (ANN)            │
           │  - Structure walk (PPR)          │
           │  - Rerank + blend + explain      │
           │  - Trace back to all sources     │
           └──────────────────────────────────┘
```

## Key Concepts

- **Content-Addressed Everything:**
  - All raw sources, blobs, text extractions, and semantic chunks are addressed by their hash.
  - Multiple sources can point to the same underlying blob/chunk; provenance is never lost.
- **Lake and Parquet tables:**
  - `sources.parquet` — metadata + original path/URL/headers
  - `blobs.parquet` — raw bytes (zstd) + hashes
  - `extractions.parquet` — decoded/normalized text
  - `chunks.parquet` — semantic chunks for retrieval
  - `embeddings.parquet` — vectors for each chunk/document
- **Neo4j as "engine graph":**
  - Nodes: `:Doc`, `:Chunk`, `:Entity`, `:Run`, `:Query`
  - Edges: `HAS_CHUNK`, `SIMILAR_TO` (kNN), `MENTIONS`, `PRODUCED`, etc.
  - Vector index for fast similarity search
  - GDS (Graph Data Science) for enrichment (PageRank, communities, density, etc.)
- **Lineage and Logging:**
  - Every ETL/job/run is logged both as a JSONL append-only log and as a `:Run` node in the graph.
  - All transformations, chunking, deduplication, and indexing steps are non-destructive—provenance is always queryable.

## Data Flow in English

1. **Ingest:**
   Scan files/web/API, extract metadata, compute hashes, store as blobs (zstd-compressed), and log all source info.
2. **Extract & Normalize:**
   Decode text, strip boilerplate, normalize encoding. Store extracted text, link to blob.
3. **Chunk & Embed:**
   Cut into semantic chunks (e.g., 800 tokens, 200 overlap), embed each chunk with model of choice. Store all in Parquet.
4. **Graph Load:**
   Upsert docs/chunks/entities to Neo4j.
   Build `SIMILAR_TO` edges with GDS kNN, compute density, run structure walks (PPR).
5. **Query & Synthesis:**
   Search via ANN vector seeds, expand with Personalized PageRank, blend/rerank results, and always allow user to "explain" a result by tracing provenance all the way back.

## Scaling/Modularity Notes

- Only the "hot set" goes to graph/vector index:
  Archive everything, but only promote the active/important stuff to Neo4j and vector search.
  Rest stays in Parquet, ready for "rehydration."
- Easily swap/extend:
  Can move embedding, chunking, graph, and object storage to separate services as load grows.
  Graph engine can be swapped for JanusGraph/NebulaGraph/etc. later without changing ingest logic.

## Example Schema Snippet (Cypher)

```cypher
CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Doc) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE;
CREATE INDEX idx_chunk_embed IF NOT EXISTS FOR (c:Chunk) ON (c.embedding)
  OPTIONS {indexProvider:'vector-1.0', indexConfig:{'vector.dimensions':768, 'vector.similarity_function':'cosine'}};
CALL db.index.fulltext.createNodeIndex('idx_chunk_fulltext',['Chunk'],['text','title']);
```

