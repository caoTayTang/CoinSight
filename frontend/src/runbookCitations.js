// Link only citation IDs backed by this response's retrieved evidence.
export function runbookSources(evidence) {
  const sources = new Map();
  const walk = (entries, depth = 0) => {
    if (depth > 3 || !Array.isArray(entries)) return;
    for (const entry of entries.slice(0, 32)) {
      const result = entry?.result;
      if (entry?.tool === 'search_runbooks' && result?.status === 'available' && Array.isArray(result.hits)) {
        for (const hit of result.hits.slice(0, 5)) {
          if (sources.size >= 40) break;
          if (typeof hit?.citation !== 'string' || !/^\[runbook:[a-z0-9_]+:\d+:\d+\]$/.test(hit.citation) ||
              typeof hit.text !== 'string' || typeof hit.title !== 'string' || typeof hit.source !== 'string' ||
              !/^[a-f0-9]{64}$/.test(hit.sha256)) continue;
          if (!sources.has(hit.citation)) sources.set(hit.citation, {
            citation: hit.citation, title: hit.title.slice(0, 300), text: hit.text.slice(0, 1600),
            source: hit.source.slice(0, 300), sha256: hit.sha256,
          });
        }
      }
      if (entry?.tool === 'investigate_warehouse') walk(result?.result?.evidence, depth + 1);
    }
  };
  walk(evidence);
  return [...sources.values()];
}

export function citationLinks(links) {
  return () => tree => {
    const walk = node => {
      if (!Array.isArray(node.children) || ['link', 'linkReference', 'code', 'inlineCode', 'html'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if (child.type !== 'text') { walk(child); return [child]; }
        const pieces = []; let start = 0;
        for (const match of child.value.matchAll(/\[runbook:[a-z0-9_]+:\d+:\d+\]/g)) {
          const href = links.get(match[0]);
          if (!href) continue;
          if (match.index > start) pieces.push({type: 'text', value: child.value.slice(start, match.index)});
          pieces.push({type: 'link', url: href, children: [{type: 'text', value: match[0]}]});
          start = match.index + match[0].length;
        }
        if (start < child.value.length) pieces.push({type: 'text', value: child.value.slice(start)});
        return pieces;
      });
    };
    walk(tree);
  };
}
