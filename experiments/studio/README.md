# clstrfck Studio

A functional prototype for collecting material from documents and using it to write resumes and other personal documents.

**Status:** experimental implementation intended for real, limited use. Much of this code is expected to be replaced. The lasting outputs are the user's documents, portable workspace data, and the product understanding gained from using it.

## Immediate goal

Get existing career material into a usable workspace, find useful passages, collect them into projects, edit them, and export finished writing. Prioritize that workflow and preservation of the user's work.

The broader clstrfck project explores a local-first personal knowledge graph with traceable derivations. This prototype helps discover its workflows and requirements. Its implementation and data model are provisional.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | Current application, including HTML, styles, demo data, and JavaScript |
| `README.md` | Purpose, operation, current capabilities, and boundaries |
| `scratchpad.md` | Agent handoff, inspected implementation details, next increments, and session notes |

## Run locally

From the repository root, with Python 3 installed:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory experiments/studio
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/).

The current version needs no build step. The server serves the application files; it is not a document-processing backend. Select personal documents through the application's import controls.

Use the same browser profile, host, and port to return to the same browser workspace. A hosted copy and this local copy have separate browser storage. Moving the HTML file does not transfer saved work between origins.

## Current capabilities

Baseline inspected on 2026-10-18; update this section as work lands.

- Search and filter the sample archive and imported text.
- Import individual TXT and Markdown files.
- Collect material into projects with their own briefs.
- Inspect source text and paragraph locations.
- Assemble drafts and edit source-linked blocks.
- Copy material and export Markdown.
- Archive and restore projects and source documents.
- Review and perform removals within the prototype workspace.
- Use a focused editor window, a collapsible sidebar, and theme/contrast settings.

The current retrieval and tagging use lightweight rules and matching. Imported text is split into paragraphs; importing it does not automatically build the full semantic graph described in the design notes.

## Current limits

- Import accepts TXT and Markdown, with a 400,000-byte file-size check.
- The model also checks text length and creates at most 80 paragraph records per imported document. Paragraphs shorter than 16 JavaScript string units are skipped.
- Paths are reduced to filenames and flattened.
- State is serialized into `localStorage`.
- Source offsets describe positions in the stored text. They do not establish a mapping to original PDF or Word layout.
- Nested folder import, PDF/DOCX extraction, IndexedDB persistence, and full workspace export/restore are planned.
- Existing Markdown exports are document outputs, not complete workspace backups.

Archive and removal act on copies and records held by this prototype. They do not modify the original files selected from the computer.

## Next useful increments

See [scratchpad.md](scratchpad.md) for the detailed handoff and acceptance checks.

1. Add folder selection and recursive drop import for TXT/Markdown, retaining relative paths and reporting every file outcome.
2. Add versioned workspace export/restore so collections, edits, and source links can be carried forward.
3. Move saved workspace content to IndexedDB before using a substantial archive, preserving existing work and editor-window behavior.
4. Add PDF text extraction and DOCX text extraction.
5. Use real workflows to identify the next necessary improvements. Record those discoveries separately from implementation shortcuts.

OCR, live folder watching, direct edits to original documents, and advanced semantic retrieval are future work.

## Implementation boundaries

Keep prototype-specific UI, import, storage, and tests within `experiments/studio/`. Add files or dependencies here when they solve a concrete need; the initial single-file arrangement is convenient, not mandatory.

Existing libraries may be used where that immediately helps. Production application code must not depend on this experiment. Promote a useful behavior or interface into the design notes after it has been exercised; shared code requires a separate deliberate decision.

Treat the working backend spec as a discussion draft. Proposed architecture is not an instruction to implement every subsystem before the resume workflow can be used.

## Working data

Keep personal documents, extracted content, workspace backups, and resume drafts outside tracked source. Use fictional fixtures for committed checks. If using a local data directory within the repository, verify its ignore rules.

Imported content and parser output are untrusted input. Render text safely and keep processing local. Follow the repository's existing review and pre-push checks.

Before storage migrations or destructive workspace operations, provide a recoverable export. Show save failures explicitly; a working screen alone does not mean data was persisted.

## Agent handoff

Read this file and [scratchpad.md](scratchpad.md), then inspect the current checkout and its applicable instructions. Complete useful increments, verify the behavior changed, and update both documents to reflect the actual result.

The current handoff documents are implementation guidance. They do not indicate that the planned import and persistence changes have already been made.

