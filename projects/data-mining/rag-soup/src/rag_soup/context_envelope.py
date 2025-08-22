def render_context(docs, boundary="-----8<-----"):
    lines = ["[CONTEXT-BLOCK v1]"]
    for d in docs:
        lines.append(f'<doc id="{d.doc_uid}" chunk="{d.chunk_id}" title="" source="" ts="">')
        lines.append("<pre>")
        lines.append(d.text if hasattr(d, "text") else "")
        lines.append("</pre>")
        lines.append("</doc>")
        lines.append(boundary)
    lines.append("END OF CONTEXT-BLOCK")
    return "\n".join(lines)
