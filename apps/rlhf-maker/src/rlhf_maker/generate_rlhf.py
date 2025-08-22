#!/usr/bin/env python3
import json, re, argparse, os
from pathlib import Path
from datetime import datetime, timezone

URL_RE = re.compile(r'https?://[^\s")]+', re.IGNORECASE)
CORRECTION_RE = re.compile(
    r"^(no(?!w)\b|nah\b|not exactly|that's not|that’s not|incorrect|wrong|what\?|huh|does(?:n’t|n't)\s+answer|you didn(?:’|')t|clarify|correction)",
    re.IGNORECASE,
)
APOLOGY_RE = re.compile(r"\b(sorry|my bad|apologize)\b", re.IGNORECASE)

def to_iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None

def extract_urls(obj, urls):
    if isinstance(obj, dict):
        for v in obj.values():
            extract_urls(v, urls)
    elif isinstance(obj, list):
        for v in obj:
            extract_urls(v, urls)
    elif isinstance(obj, str):
        urls.update(URL_RE.findall(obj))

def extract_text_from_content(content):
    if not isinstance(content, dict):
        return "", []
    ct = content.get("content_type")
    parts = content.get("parts", [])
    texts, types = [], []
    if ct in ("text", "multimodal_text", "tool_result", "code", "json", "user_editable_context"):
        for p in parts:
            if isinstance(p, dict):
                pt = p.get("content_type")
                types.append(pt or "dict")
                if "text" in p:
                    texts.append(str(p["text"]))
            elif isinstance(p, str):
                texts.append(p); types.append("str")
    return "\n".join(t for t in texts if t is not None).strip(), types

def extract_assets(parts):
    assets = []
    for p in parts or []:
        if isinstance(p, dict):
            ct = p.get("content_type")
            if ct and ct.endswith("_asset_pointer"):
                assets.append({
                    "content_type": ct,
                    "format": p.get("format"),
                    "size_bytes": p.get("size_bytes"),
                    "asset_pointer": p.get("asset_pointer"),
                })
            if ct == "real_time_user_audio_video_asset_pointer":
                ap = p.get("audio_asset_pointer") or {}
                if ap.get("asset_pointer"):
                    assets.append({
                        "content_type": "audio_asset_pointer",
                        "format": ap.get("format"),
                        "size_bytes": ap.get("size_bytes"),
                        "asset_pointer": ap.get("asset_pointer"),
                    })
    return assets

def sort_children(mapping, ids):
    def key(cid):
        msg = (mapping.get(cid) or {}).get("message") or {}
        ts = msg.get("create_time")
        try:
            return (float(ts), cid)
        except Exception:
            return (1e300, cid)
    return sorted(ids, key=key)

def walk_conv(conv):
    """Return ordered list of nodes (seq order) with normalized fields."""
    mapping = conv.get("mapping", {})
    if not mapping:
        return []

    roots = [nid for nid, node in mapping.items() if node.get("parent") is None]
    visited, ordered = set(), []

    def walk(nid, depth):
        if nid in visited: return
        visited.add(nid)
        node = mapping.get(nid, {}) or {}
        msg = node.get("message") or {}
        author = msg.get("author") or {}
        role = author.get("role")
        author_name = author.get("name")
        recipient = msg.get("recipient")
        content = msg.get("content") or {}
        text, part_types = extract_text_from_content(content)
        assets = extract_assets(content.get("parts", []))
        urls = set(); extract_urls(node, urls)

        tool_call = (role == "assistant" and recipient not in (None, "all"))
        tool_result = (role == "tool")
        tool_name = None
        if tool_call:
            tool_name = recipient
        elif tool_result and author_name:
            tool_name = author_name

        ordered.append({
            "node_id": nid,
            "parent_id": node.get("parent"),
            "depth": depth,
            "role": role,
            "author_name": author_name,
            "recipient": recipient,
            "tool_call": tool_call,
            "tool_result": tool_result,
            "tool_name": tool_name,
            "type": content.get("content_type"),
            "part_types": part_types,
            "text": text,
            "assets": assets,
            "urls": sorted(urls),
            "create_time": msg.get("create_time"),
            "create_time_iso": to_iso(msg.get("create_time")),
            "status": msg.get("status"),
            "end_turn": msg.get("end_turn"),
            "raw_content": content,  # keep full for tools
        })
        for cid in sort_children(mapping, node.get("children") or []):
            walk(cid, depth + 1)

    for r in sort_children(mapping, roots):
        walk(r, 0)

    # add seq
    for i, r in enumerate(ordered):
        r["seq"] = i
    return ordered

def make_segments(ordered, max_exchanges=3):
    """
    Build SFT segments of up to `max_exchanges` (user->assistant pairs),
    keeping tools in-between as messages.
    """
    # collect indices where user speaks (anchors)
    user_idxs = [i for i, r in enumerate(ordered) if r["role"] == "user"]
    segments = []
    for ui in user_idxs:
        # consume up to N exchanges from here
        msgs = []
        exchanges = 0
        # include context above if you want longer windows; here we start at ui
        i = ui
        while i < len(ordered) and exchanges < max_exchanges:
            r = ordered[i]
            msgs.append(r)
            if r["role"] == "assistant" and r.get("end_turn") in (True, None):
                exchanges += 1
            i += 1
        if len(msgs) >= 2:
            segments.append(msgs)
    return segments

def msgs_to_sft(messages, conv_id=None):
    out = []
    for r in messages:
        if r["tool_call"]:
            out.append({"role":"assistant", "tool_call":{
                "name": r.get("tool_name") or (r.get("recipient") or "tool"),
                "arguments": r.get("raw_content")  # raw content JSON as args
            }})
        elif r["tool_result"]:
            out.append({"role":"tool", "name": r.get("tool_name") or "tool",
                        "content": r.get("raw_content")})
        else:
            if r["role"] in ("system","user","assistant"):
                content = r["text"] or ""
                out.append({"role": r["role"], "content": content})
            # ignore other roles silently
    return {
        "messages": out,
        "meta": {
            "conv_id": conv_id,
            "start_seq": messages[0]["seq"],
            "end_seq": messages[-1]["seq"],
            "has_tools": any(m.get("tool_call") or m.get("tool_result") for m in messages),
        }
    }

def make_pairs(ordered, lookahead=6):
    """
    Produce (prompt, rejected, chosen) triples using simple heuristics:
    - If a user correction follows an assistant, pair the assistant reply (rejected)
      with the *next* assistant reply after that correction (chosen).
    - If an assistant apologizes and then produces a new answer, first is rejected, second is chosen.
    """
    pairs = []
    n = len(ordered)
    for i, r in enumerate(ordered):
        # assistant -> user correction
        if r["role"] == "assistant" and (r.get("text") or ""):
            # find next few turns
            j_end = min(n, i + 1 + lookahead)
            # look for immediate user correction
            corr_j = None
            for j in range(i+1, j_end):
                if ordered[j]["role"] == "user":
                    txt = (ordered[j].get("text") or "").strip()
                    if CORRECTION_RE.search(txt):
                        corr_j = j; break
                    # if user says "ok/thanks", likely NOT a correction
                    if re.search(r"\b(thanks|ok|great|got it)\b", txt, re.I):
                        break
            if corr_j is not None:
                # find the next assistant after the correction
                chosen_k = None
                for k in range(corr_j+1, j_end):
                    if ordered[k]["role"] == "assistant" and (ordered[k].get("text") or ""):
                        chosen_k = k; break
                if chosen_k is not None:
                    # prompt is context up to correction's user message
                    ctx = []
                    for t in range(max(0, i-6), corr_j+1):
                        rr = ordered[t]
                        # include plain roles + tools if you want tool-aware RM
                        if rr["tool_call"]:
                            ctx.append({"role":"assistant","tool_call":{
                                "name": rr.get("tool_name") or (rr.get("recipient") or "tool"),
                                "arguments": rr.get("raw_content")
                            }})
                        elif rr["tool_result"]:
                            ctx.append({"role":"tool","name": rr.get("tool_name") or "tool",
                                        "content": rr.get("raw_content")})
                        elif rr["role"] in ("system","user","assistant"):
                            ctx.append({"role": rr["role"], "content": rr.get("text") or ""})
                    pairs.append({
                        "prompt_messages": ctx,
                        "rejected": ordered[i]["text"],
                        "chosen": ordered[chosen_k]["text"],
                        "signals": {"user_correction": True},
                        "meta": {"rejected_seq": i, "chosen_seq": chosen_k}
                    })
            # assistant apology -> next assistant
            txta = (r.get("text") or "")
            if APOLOGY_RE.search(txta):
                next_ass = None
                for k in range(i+1, j_end):
                    if ordered[k]["role"] == "assistant" and (ordered[k].get("text") or ""):
                        next_ass = k; break
                if next_ass is not None:
                    ctx = []
                    # prompt is context up to the *previous* user message
                    up_to = i
                    for t in range(max(0, i-6), up_to+1):
                        rr = ordered[t]
                        if rr["tool_call"]:
                            ctx.append({"role":"assistant","tool_call":{
                                "name": rr.get("tool_name") or (rr.get("recipient") or "tool"),
                                "arguments": rr.get("raw_content")
                            }})
                        elif rr["tool_result"]:
                            ctx.append({"role":"tool","name": rr.get("tool_name") or "tool",
                                        "content": rr.get("raw_content")})
                        elif rr["role"] in ("system","user","assistant"):
                            ctx.append({"role": rr["role"], "content": rr.get("text") or ""})
                    pairs.append({
                        "prompt_messages": ctx,
                        "rejected": r["text"],
                        "chosen": ordered[next_ass]["text"],
                        "signals": {"apology_followup": True},
                        "meta": {"rejected_seq": i, "chosen_seq": next_ass}
                    })
    return pairs

def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def parse_dump(obj):
    """Accept a single conversation dict or a list (export that contains one)."""
    convs = obj if isinstance(obj, list) else [obj]
    out = []
    for conv in convs:
        cid = conv.get("conversation_id") or conv.get("title")
        ordered = walk_conv(conv)
        for r in ordered:
            r["conv_id"] = cid
        out.append((cid, ordered))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "-i", required=True, help="Path to a single JSON export or a directory of dumps")
    ap.add_argument("--outdir", "-o", default="out_rlhf", help="Where to write datasets")
    ap.add_argument("--max-exchanges", type=int, default=3, help="SFT: number of user->assistant exchanges per sample")
    args = ap.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    dump_paths = []
    if inp.is_dir():
        dump_paths = sorted([p for p in inp.glob("*.json")])
    else:
        dump_paths = [inp]

    all_sft, all_pairs, all_tools = [], [], []

    for p in dump_paths:
        with p.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        for conv_id, ordered in parse_dump(obj):
            # SFT segments
            segs = make_segments(ordered, max_exchanges=args.max_exchanges)
            for seg in segs:
                all_sft.append(msgs_to_sft(seg, conv_id=conv_id))
            # Pairs
            pairs = make_pairs(ordered)
            for pr in pairs:
                pr["meta"]["conv_id"] = conv_id
            all_pairs.extend(pairs)
            # Tools
            for r in ordered:
                if r.get("tool_call") or r.get("tool_result"):
                    all_tools.append({
                        "conv_id": conv_id,
                        "seq": r["seq"],
                        "tool_name": r.get("tool_name") or (r.get("recipient") or "tool"),
                        "direction": "call" if r.get("tool_call") else "result",
                        "payload": r.get("raw_content"),
                        "text_preview": (r.get("text") or "")[:200],
                        "urls": r.get("urls", []),
                        "time": r.get("create_time_iso")
                    })

    # Write files
    write_jsonl(outdir / "sft.jsonl", all_sft)
    write_jsonl(outdir / "dpo_pairs.jsonl", all_pairs)
    write_jsonl(outdir / "tool_traces.jsonl", all_tools)

    print(f"Wrote: {len(all_sft)} SFT segments, {len(all_pairs)} pairs, {len(all_tools)} tool rows to {outdir}/")

if __name__ == "__main__":
    main()
