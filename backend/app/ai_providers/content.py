"""Provider-neutral reading of stored message content.

Conversation history keeps assistant turns as a list of content blocks
(``{"type": "text", "text": ...}`` or SDK objects with the same fields). Both
adapters read text out of that shape, so it lives here rather than in either
provider module.
"""


def block_text(content_blocks):
    out = []
    for block in (content_blocks or []):
        if isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                out.append(str(block.get("text")))
            continue
        if getattr(block, "type", None) == "text":
            block_text_value = getattr(block, "text", "")
            if block_text_value:
                out.append(str(block_text_value))
    return "\n".join(out).strip()
