def strip_markdown_fence(raw: str) -> str:
    """Remove a single outer markdown code fence (``` or ```lang) from an LLM response."""
    raw = raw.strip()
    if not raw.startswith("```"):
        return raw
    # Drop the opening fence line
    first_newline = raw.find("\n")
    if first_newline == -1:
        return raw
    raw = raw[first_newline + 1 :]
    # Find the closing fence as its own line to avoid matching embedded ``` in content
    for i, line in enumerate(raw.splitlines()):
        if line.strip() == "```":
            return "\n".join(raw.splitlines()[:i])
    return raw
