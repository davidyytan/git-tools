"""Conservative single-layer response-envelope detection; never rewrite inner content."""

import re

_NAME = r"[A-Za-z_][\w:.-]*"
_ATTRIBUTES = rf'''(?:\s+{_NAME}\s*=\s*(?:"[^"]*"|'[^']*'))*'''
_OPENING = re.compile(rf"<(?P<tag>{_NAME}){_ATTRIBUTES}\s*(?P<empty>/)?>")
# Ordinary HTML roots remain document markup; output/template are intentional reply-envelope names.
_DOCUMENT_ROOTS = frozenset("a abbr address area article aside audio b base bdi bdo blockquote body br button canvas caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link main map mark menu meta meter nav noscript object ol optgroup option output p picture pre progress q rp rt ruby s samp script search section select slot small source span strong style sub summary sup table tbody td template textarea tfoot th thead time title tr track u ul var video wbr svg math".split()) - {"output", "template"}


def unwrap_outer_xml_response(content: str) -> str | None:
    """Remove one complete outer XML-style envelope, or return None without guessing."""
    if not content.lstrip().startswith("<"):
        return None
    first_line = next((line for line in content.splitlines() if line.strip()), "")
    indentation = re.match(r"[ \t]*", first_line).group()
    if len(indentation.expandtabs(4)) >= 4:
        return None  # Markdown code indentation uses four-column tab stops; preserve it verbatim.
    text = content.strip()
    start = 0
    if text.startswith("<?xml"):
        declaration = re.match(r"<\?xml\s[^?]*\?>\s*", text)
        if declaration is None:
            return None
        start = declaration.end()
    opening = _OPENING.match(text, start)
    if opening is None:
        return None
    tag = opening.group("tag")
    if tag.rsplit(":", 1)[-1].lower() in _DOCUMENT_ROOTS:
        return None
    if opening.group("empty"):
        return "" if opening.end() == len(text) else None
    closing = re.search(rf"</{re.escape(tag)}\s*>\Z", text)
    if closing is None:
        return None
    # Balance this wrapper name only. Markdown, entities and all other inner markup remain verbatim.
    tokens = re.compile(rf"</{re.escape(tag)}\s*>|<{re.escape(tag)}(?=[\s/>]){_ATTRIBUTES}\s*/?>")
    depth = 1
    for token in tokens.finditer(text, opening.end()):
        if token.group().startswith("</"):
            depth -= 1
            if depth == 0:
                if token.start() != closing.start() or token.end() != closing.end():
                    return None  # Multiple adjacent blocks are not one outer wrapper.
                break
        elif not token.group().endswith("/>"):
            depth += 1
    if depth != 0:
        return None
    payload = text[opening.end():closing.start()]
    # Like a code-fence line ending, remove only one marker-owned separator at each edge.
    if payload.startswith("\r\n"):
        payload = payload[2:]
    elif payload.startswith(("\n", "\r")):
        payload = payload[1:]
    if payload.endswith("\r\n"):
        payload = payload[:-2]
    elif payload.endswith(("\n", "\r")):
        payload = payload[:-1]
    return payload
