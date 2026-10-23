// Link only skill citations backed by a load_skill call in this response's evidence.
const CITATION = /\[skill:[a-z0-9]+(?:-[a-z0-9]+)*\]/g;
export function skillSources(evidence) {
  const sources = new Map();
  const walk = (entries, depth = 0) => {
    if (depth > 3 || !Array.isArray(entries)) return;
    for (const entry of entries.slice(0, 32)) {
      const result = entry?.result;
      if (entry?.tool === 'load_skill' && result?.status === 'available' && sources.size < 20 &&
          typeof result.citation === 'string' && /^\[skill:[a-z0-9]+(?:-[a-z0-9]+)*\]$/.test(result.citation) &&
          typeof result.description === 'string' && typeof result.instructions === 'string' &&
          typeof result.source === 'string' && /^[a-f0-9]{64}$/.test(result.sha256) && !sources.has(result.citation)) {
        sources.set(result.citation, {
          citation: result.citation, title: String(result.name).slice(0, 80), description: result.description.slice(0, 400),
          text: result.instructions.slice(0, 4000), source: result.source.slice(0, 300), sha256: result.sha256,
        });
      }
      if (entry?.tool === 'investigate_warehouse') walk(result?.result?.evidence, depth + 1);
    }
  };
  walk(evidence);
  return [...sources.values()];
}

// "[skill:forecast-explainer]" -> "Forecast explainer"
export function skillLabel(citation) {
  const words = citation.slice(7, -1).replace(/-/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function citationLinks(links) {
  return () => tree => {
    const walk = node => {
      if (!Array.isArray(node.children) || ['link', 'linkReference', 'code', 'inlineCode', 'html'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if (child.type !== 'text') { walk(child); return [child]; }
        const pieces = []; let start = 0;
        for (const match of child.value.matchAll(CITATION)) {
          const href = links.get(match[0]);
          if (!href) continue;
          if (match.index > start) pieces.push({type: 'text', value: child.value.slice(start, match.index)});
          pieces.push({type: 'link', url: href, children: [{type: 'text', value: skillLabel(match[0])}]});
          start = match.index + match[0].length;
        }
        if (start < child.value.length) pieces.push({type: 'text', value: child.value.slice(start)});
        return pieces;
      });
    };
    walk(tree);
  };
}
