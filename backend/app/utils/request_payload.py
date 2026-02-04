def extract_user_text(data):
    """Return a clean user text from varied payload shapes."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        # direct
        for k in ("message","user_message","prompt","text","content"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                for kk in ("text","content","message"):
                    vv = v.get(kk)
                    if isinstance(vv, str) and vv.strip():
                        return vv.strip()
        # chat arrays (OpenAI/Anthropic)
        msgs = data.get("messages") or data.get("history")
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if not isinstance(m, dict): 
                    continue
                role = m.get("role")
                content = m.get("content")
                if role in ("user","human") and isinstance(content, str) and content.strip():
                    return content.strip()
                if role in ("user","human") and isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            t = part.get("text")
                            if isinstance(t, str) and t.strip():
                                return t.strip()
    # last resort: small JSON preview
    try:
        import json
        s = json.dumps(data, ensure_ascii=False)
        return s[:1000].strip()
    except Exception:
        return ""
