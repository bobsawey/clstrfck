# Chat Conversation Viewer — README

A single‑file web app (open `index.html`) for browsing your ChatGPT conversation exports. Load one or many JSON files, navigate conversations, inspect message metadata, tool calls/results, URLs, and export a simple SFT‑style JSONL for the current conversation.

---

## ✨ Features

- **Drop‑in viewer:** Just open `index.html` in a browser—no server, no build tools.
- **Multi‑file import:** Upload or drag‑drop one or many `.json` files.
- **Graph → timeline:** Parses the ChatGPT `mapping` graph (parent/children) into an ordered turn list.
- **Message inspector:** Role, timestamp, text (incl. voice transcriptions), part types, assets, URLs, raw content, and metadata.
- **Tool awareness:** Distinguishes **tool calls** and **tool results** and shows the tool name.
- **Search & filters:** Filter conversations and messages; toggle tool‑only view; optional thread **Tree view**.
- **Export:** One‑click **SFT JSONL** export of the current conversation (messages with tool traces).
- **Sample data:** "Load sample" button to try the UI.

---

## 🧩 Supported JSON shapes

The viewer accepts either of the following at the top level:

1. **Single conversation object** with a `mapping` and `children` pointers.
2. **Array of conversations**, each with a `mapping`.

Minimal expected structure inside each conversation object:

```json
{
  "title": "…",
  "create_time": 1753476833.0443,
  "update_time": 1753481312.8703,
  "mapping": {
    "<uuid/root>": {
      "id": "…",
      "message": null,
      "parent": null,
      "children": ["<child-id>"]
    },
    "<child-id>": {
      "id": "…",
      "message": {
        "author": {"role": "user|assistant|tool|system", "name": null},
        "create_time": 1753476832.82,
        "content": {
          "content_type": "text|multimodal_text|tool_result|json|code|user_editable_context",
          "parts": [
            {"content_type": "audio_transcription", "text": "…"}
          ]
        },
        "recipient": "all|<tool-name>",
        "end_turn": true
      },
      "parent": "<uuid/root>",
      "children": []
    }
  }
}
```

### How tools are detected

- **Tool call:** `author.role === "assistant"` **and** `recipient !== "all"` → `tool_name = recipient`.
- **Tool result:** `author.role === "tool"` → `tool_name = author.name`.

### What text is displayed

From `content.parts`, the viewer collects strings and any objects with a `text` field (e.g., `audio_transcription`, `text`, `json`, `code`).

### URL and asset extraction

- **URLs:** Regex‑scan of the entire node (message, metadata, payloads).
- **Assets:** Any part with `*_asset_pointer` or a real‑time bundle’s `audio_asset_pointer` is surfaced.

---

## 🚀 Quick start

1. Save the HTML from the canvas as `index.html`.
2. Open it in a modern browser (Chrome/Edge/Firefox/Safari). No server needed.
3. **Load data:**
   - Click **Choose File** and select one or more `.json` exports, or
   - Drag‑and‑drop JSON files onto the **Drop** area.
4. Click a conversation in the left pane to view its messages.
5. Use the **search** box to filter messages; enable **Show only tool turns** or **Tree view** as needed.
6. Click **Export SFT JSONL** to download a messages‑style JSONL for the current conversation.

---

## 📤 Export format (SFT JSONL)

Each line contains a minimal `{ messages, meta }` structure. The viewer emits **one line per turn**, preserving tool traces as messages:

```json
{"messages":[{"role":"user","content":"…"}],"meta":{"conv_id":"…","seq":12}}
{"messages":[{"role":"assistant","content":"…"}],"meta":{"conv_id":"…","seq":13}}
{"messages":[{"role":"assistant","tool_call":{"name":"web","arguments":{…}}}],"meta":{"conv_id":"…","seq":14}}
{"messages":[{"role":"tool","name":"web","content":{…}}],"meta":{"conv_id":"…","seq":15}}
```

> Note: This is a **flat turn list** for quick SFT experiments. If you want multi‑turn windows or DPO/RM pairs, see the “Extending” section below.

---

## 🔍 UI reference

- **Conversation search:** Filters by `title`/`id`.
- **Message search:** Full‑text over role, tool name, recipient, message text, and URLs.
- **Tree view:** Shows the thread structure as parsed from `parent → children`.
- **Tool badges:** "tool call" / "tool result" and the detected `content_type`.
- **Details → Raw content / Metadata:** Expand to view original JSON for the turn.

---

## 🧪 Known limitations

- **Read‑only:** This is a viewer—no editing or writing back to the source.
- **Very large dumps:** Extremely big mappings may render slowly in the browser.
- **Text extraction:** Only fields with `text` in `content.parts` are shown. Non‑textual payloads render under **Raw content**.
- **Timestamps:** Expect UNIX seconds; malformed values render as `—`.

---

## 🧰 Extending the tool

A few easy additions if you want more:

- **DPO/RM export:** Group turns into prompt/chosen/rejected triples via heuristics (user corrections, apology‑followups) and download as `pairs.jsonl`.
- **TSV/CSV export of current view:** Serialize the visible rows with flattened `urls`, `assets`, and `part_types`.
- **URL bucketing:** Split into `search`, `citations`, `other` based on payload/metadata shapes.
- **Audio previews:** If you store accessible blob URLs for `asset_pointer`, add inline audio players (security permitting).

---

## 🔐 Privacy

Everything runs client‑side. Files never leave your machine unless you export them. Open locally and work offline if you prefer.

---

## ❓ Troubleshooting

- **“Failed to parse …”**: Your file isn’t valid JSON, or the top‑level isn’t an object/array. Re‑export or validate the JSON.
- **No messages show up**: Ensure the dump contains a `mapping` with nodes linked by `parent`/`children`, and each message has an `author.role`.
- **Tools not detected**: Check that assistant tool calls set `recipient` to the tool name and tool results use `author.role: "tool"` with `author.name`.

---

## 📜 License

Do whatever you want. Attribution appreciated if you share it.

