"""Conservative single-layer response-envelope detection; never rewrite inner content."""

import re

_NAME = r"[A-Za-z_][\w:.-]*"
_ATTRIBUTES = rf'''(?:\s+{_NAME}\s*=\s*(?:"[^"]*"|'[^']*'))*'''
_OPENING = re.compile(rf"<(?P<tag>{_NAME}){_ATTRIBUTES}\s*(?P<empty>/)?>")
# Known HTML roots, including obsolete/browser-legacy elements, remain markup; output/template are intentional reply-envelope names.
_DOCUMENT_ROOTS = frozenset("a abbr acronym address applet area article aside audio b base basefont bdi bdo bgsound big blink blockquote body br button canvas caption center cite code col colgroup command content data datalist dd del details dfn dialog dir div dl dt em embed fieldset figcaption figure font footer form frame frameset h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe image img input ins isindex kbd keygen label legend li link listing main map mark marquee math menu menuitem meta meter multicol nav nextid nobr noembed noframes noscript object ol optgroup option output p param picture plaintext pre progress q rb rp rt rtc ruby s samp script search section select shadow slot small source spacer span strike strong style sub summary sup svg table tbody td template textarea tfoot th thead time title tr track tt u ul var video wbr xmp".split()) - {"output", "template"}


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
