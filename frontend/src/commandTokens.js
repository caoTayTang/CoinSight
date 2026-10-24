import {deskCommands} from './deskCommands.js';

// Real @agent and /command tokens; anything else stays plain text.
const TOKEN = /(^|\s)([@/][a-z]+)(?=[\s.,;:!?)]|$)/gi;

export function commandFor(token) {
  const key = token.toLowerCase();
  return deskCommands.find(c => c.token === key) || null;
}

// "ask @sre now" -> ['ask ', {token:'@sre', label}, ' now']
export function splitCommands(text) {
  const parts = []; let start = 0;
  for (const match of String(text).matchAll(TOKEN)) {
    const command = commandFor(match[2]);
    if (!command) continue;
    const at = match.index + match[1].length;
    if (at > start) parts.push(text.slice(start, at));
    parts.push({token: match[2], label: command.label});
    start = at + match[2].length;
  }
  if (start < text.length) parts.push(text.slice(start));
  return parts;
}

export const COMMAND_HREF = '#command:';

// Remark plugin: known tokens in text, or alone in inline code, become links the response renders as chips.
export function commandLinks() {
  return tree => {
    const link = token => ({type: 'link', url: COMMAND_HREF + token, children: [{type: 'text', value: token}]});
    const walk = node => {
      if (!Array.isArray(node.children) || ['link', 'linkReference', 'code', 'html'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if (child.type === 'inlineCode') return commandFor(child.value.trim()) && /^[@/][a-z]+$/i.test(child.value.trim()) ? [link(child.value.trim())] : [child];
        if (child.type !== 'text') { walk(child); return [child]; }
        return splitCommands(child.value).map(part => typeof part === 'string' ? {type: 'text', value: part} : link(part.token));
      });
    };
    walk(tree);
  };
}
