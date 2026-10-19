# Studio agent scratchpad

Updated: 2026-10-18  
Working area: `experiments/studio/`  
Purpose: handoff to Claude Opus and, later, Codex or another coding agent.

## Start here

The owner needs a useful document workbench now, especially for resume work. Extend the existing functional UI enough to support that task. The implementation is intentionally disposable; keep user work portable and record discoveries that may inform the eventual application.

Read `README.md`, applicable repository/agent instructions, and the current source before editing. Check the active branch and working tree. Preserve unrelated user changes and use the user's selected branch; the branch named below is the inspected baseline, not an instruction to switch branches or reset a checkout.

The owner prefers direct progress on routine implementation choices. Keep scope small, explain meaningful tradeoffs, and avoid requiring the full future architecture before a practical feature can work.

## Inspected baseline

- Repository: `bobsawey/clstrfck`.
- Branch inspected: `reorg/extraction-pipeline`.
- UI path: `experiments/studio/index.html`.
- Inspected Git blob: `5674c4dc18d25878299b6c5f9195b8210237d203`.
- This file matches the latest hosted Studio source inspected during the handoff.
- At inspection, the Studio directory contained only `index.html`. These two Markdown files are additions prepared for placement beside it.
- No application code was changed as part of writing this handoff. No new runtime or browser tests were run for these documents.

If the checkout has moved on, reconcile this scratchpad with the actual code. Prior conversations reported model/DOM checks, but that is not evidence that a test suite is present in this directory or that a changed version has passed it.

## Product decisions to carry forward

- UI vocabulary: material, sources, projects, drafts. “Evidence” is a role material may play; some internal identifiers still use older names.
- Preserve the useful existing project/editor flow and appearance options.
- Project edits belong to the project. Import reads local files into a snapshot; it does not grant permission to write back to originals.
- Archive means reversible organization. Removal is a separate operation with dependent content to consider.
- Trace a block to the specific stored source text used when it was inserted.
- Keep processing and personal content local. An LLM is not required for this increment.
- Keep prototype implementation in this folder. Any promotion into production/shared code is a separate decision.
- Save real writing and workspace data in portable formats so replacing the implementation does not discard the user's work.

## Where to look in the current code

Search by symbol rather than relying on line numbers.

| Area | Current implementation |
| --- | --- |
| Base data/model | `Workbench` |
| Projects and lifecycle | `StudioModel` |
| Text ingestion | `Workbench.importText`, wrapped by `StudioModel.importText` |
| Main records | `sources`, `facts`, `families`, `projects` |
| Project collection | Project `ids` refers to families |
| Editor | `editorRows`, `insertBlock`, `editorText`, `editorReady` |
| Editor references | Blocks retain `fid`, `eid`, `sid`, and editable `text` |
| Persistence | Startup reads JSON from `localStorage`; `save()` serializes the whole state |
| Cross-window updates | A `storage` event listener reloads saved state |
| Import control | `file-input` change handler reads files with `File.text()` |
| Existing drag/drop | Handles material collection/reordering; directory drops are additional behavior |
| Source browsing | `renderSources` currently groups by the first path component |

The existing text importer already creates the source, paragraph records, and material families that the editor consumes. Adapt that connection.

### Specific limitations and assumptions

- The file picker/handler accepts TXT and Markdown and rejects files larger than 400,000 bytes.
- The model separately caps text length, skips short paragraphs, and stops after 80 paragraphs. Avoid replacing these with silent truncation.
- The importer uses the filename and replaces path separators, losing folder hierarchy.
- Identical imported text is currently rejected even if it came from a different path.
- Imported source dates currently reflect the import date. Preserve modification time separately when adding file metadata; do not imply it is the document's authorship date.
- Offsets use JavaScript string indices: UTF-16 code units into stored text, with an exclusive end. Preserve that convention for existing records or migrate it explicitly.
- `StudioModel.importText` checks removal tombstones before delegating. Preserve that policy through new import paths.
- The base assembly code contains a “Fictional demo archive” footer. Review exported labels when introducing real documents so they accurately describe the selected material.
- The UI's saved-state and focused-window behavior depend on the existing storage mechanism. IndexedDB migration must address notification/synchronization as well as writes.

## Work queue

These are proposed implementation increments, all pending at handoff. Deliver and verify them in small steps.

### 1. Nested folder import

Goal: select or drop a directory of TXT/Markdown files and use its paragraphs in the existing project editor.

- Add “Choose folder” and a folder drop target. Provide a picker fallback when directory drag/drop is unavailable.
- Enumerate nested files and retain relative paths. Keep different files with the same basename distinguishable.
- If using directory-entry readers, drain all returned batches until empty; do not assume one read returns the whole directory.
- Keep existing in-app drag/reorder interactions working.
- Share one importer between individual-file selection, folder selection, and drop.
- Preserve the complete extracted text. Retain useful headings and short bullets, and report any documented limit explicitly.
- Record relative path, size, modification time, import time, and an appropriate content hash.
- Use simple snapshot behavior: unchanged content at the same import path can be skipped; changed content creates a new source snapshot. Existing editor references continue to identify their original source.
- If identical bytes occur at different paths, preserve their distinct origins or explicit aliases.
- Report imported, duplicate, unsupported, empty, failed, and cancelled items. One bad file should not abort unrelated files.
- Use bounded processing and yield to the UI. Provide progress and a way to stop a long batch.
- Use a small fictional folder to prove the full path: import, search, collect, insert, edit, export.

### 2. Workspace export and restore

Goal: carry personal work between browsers, origins, or replacement implementations.

- Export a versioned workspace format containing sources/text, IDs and links, collections/order, project briefs, edited blocks, decisions, archive/removal state, and required counters. Include settings where useful.
- Declare precisely what is included. Once original binaries are retained, decide whether the export includes them or explicitly requires relinking them.
- Validate format version, shape, record references, and reasonable size limits before changing live state.
- Restore into a fresh workspace first. For replacement of an existing workspace, make the effect explicit and offer a backup.
- Publish a restored workspace atomically, or keep a recoverable prior copy until the new one is fully persisted.
- Preserve IDs and relationships. Keep Markdown document export alongside workspace export.
- Test a round trip in a clean browser context; comparing a backup file alone does not establish restore works.

### 3. Persistence for a real archive

Goal: use IndexedDB for substantial imported content and saved work without losing the current workspace.

- Inventory the present storage key, schema, and save/load behavior.
- Back up and migrate existing state once. Validate the migrated data before retiring any legacy copy.
- Keep old IDs, project edits, preferences, and removal records intact.
- Show whether work is saving, saved, or failed. Commit failures must not be reported as successful saves.
- Replace cross-window notifications deliberately, for example with a small invalidation signal or BroadcastChannel. Define how stale concurrent writes are rejected or handled.
- Retain each window's selected project; synchronization must not cause the focused editor and main window to overwrite one another's navigation.
- Handle quota failures and interrupted imports coherently. Keep export/restore available as a portable recovery route.
- Keeping a working in-memory model initially is acceptable. Defer larger indexing/lazy-loading work until the actual workload requires it.

### 4. PDF and Word extraction

Goal: get common career documents into the same workflow.

- Use PDF.js for text-bearing PDFs and Mammoth for DOCX as candidate local extractors; verify their current APIs and suitable pinned versions before integrating.
- Keep extracted content as text or sanitize any intentionally supported HTML.
- Keep original filenames, format, and provenance. Do not relabel a PDF as a TXT source just to pass the old extension check.
- Keep original bytes where practical and document how they are retained and backed up.
- For PDF, retain page information where available. Extraction order and line breaks may need review, especially in multi-column resumes.
- Describe anchors as positions in extracted text unless a genuine mapping to original layout is implemented.
- Report scans, encrypted files, malformed files, and unsupported formats clearly. OCR is a later increment; do not silently treat extraction failure as an empty successful import.
- Bundle required runtime assets locally so document processing can work offline once the application is available.

## Focused acceptance checks

Use fictional fixtures. Add only tests that check behavior or protect the user's work.

- Nested paths survive; two same-named files from different folders remain distinguishable.
- A directory containing more than one reader batch imports completely.
- A document beyond the old 80-paragraph cap is handled according to the stated policy, with no silent loss.
- Short bullets, headings, Unicode, and emoji preserve correct text locations.
- Reimporting unchanged material does not duplicate it accidentally; changed material does not rewrite existing draft blocks.
- Imported material can be found, collected, inserted, edited, and exported.
- Refresh retains the work; export/restore reproduces it in a fresh context.
- Old browser state migrates with project order, authored text, decisions, and source links intact.
- Main and focused editor windows retain their own navigation; stale writes do not silently erase work.
- Archive/restore and removal/tombstone behavior still work for imported material.
- Import errors, storage failures, and cancellation have visible, accurate outcomes.
- Appearance controls, sidebar collapse, and the existing editor remain usable.

Run relevant model and browser checks for the changed feature. Record the browser actually used. Distinguish automated behavior checks from visual verification and disclose anything not exercised.

## Working boundaries

Use the existing repository review and pre-push process. Personal documents, extracted content, workspace backups, real resume drafts, and logs containing private text belong outside tracked source. Keep fixtures fictional and inspect the actual diff before committing.

Keep production code independent of this experiment. Avoid expanding this task into the full graph engine, a new app framework, cloud processing, live folder synchronization, or a rewrite of the old extraction pipeline unless the user explicitly changes the scope.

The backend working spec is exploratory. Port useful findings into it as proposals or decisions; do not mistake proposed requirements for already implemented features.

## Session record

Update this after meaningful work. Replace obsolete facts rather than growing an endless transcript.

- **Current branch / commit:** Fill in from the working checkout.
- **Completed:** Handoff documents prepared; existing UI inspected.
- **Current next action:** Inspect the current importer and implement the nested-folder TXT/Markdown path.
- **Changes made:** None to application code during this handoff.
- **Checks run:** Source identity and document instructions checked; no new runtime tests.
- **Known issues / decisions:** See limitations and work queue above.
- **User work / migration status:** Inspect existing persistence before changing it.
- **Next useful step after this session:** Update to the next unfinished increment.

## Suggested opening instruction

Read experiments/studio/README.md and experiments/studio/scratchpad.md, inspect the current index.html and applicable repository instructions, and begin the next unfinished increment. Prioritize getting a local folder of documents into the existing editor and preserving my work. Keep the implementation contained in this disposable prototype, verify the behavior you change, and update the scratchpad with what actually happened.

