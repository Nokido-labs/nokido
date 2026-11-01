"""Instantane structurel des schemas d'outils (hors descriptions)."""


def structure(node):
    if isinstance(node, dict):
        out = dict()
        for k, v in node.items():
            if k == "description":
                continue
            if k == "properties":
                out[k] = dict((p, structure(s)) for p, s in v.items())
            else:
                out[k] = structure(v)
        return out
    if isinstance(node, list):
        return [structure(x) for x in node]
    return node


def snapshot(tools):
    return dict((t["name"], structure(t.get("inputSchema") or dict())) for t in tools)
