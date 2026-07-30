# Design notes

We decided to use SQLite for the index.

Benchmark FTS5 before Friday to confirm it holds up under load.

FTS5 is faster than LIKE queries for our corpus size.

Should we shard the index by year?

See https://www.sqlite.org/fts5.html for the module docs.
