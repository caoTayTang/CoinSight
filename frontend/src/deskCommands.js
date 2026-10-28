export const deskCommands = [
  {token:'@trade',command:'trade',label:'Market reasoning',hint:'@trade phân tích forecast và thống kê BTC'},
  {token:'@sre',command:'sre',label:'Warehouse / service investigation',hint:'@sre kiểm coverage BTC 24 giờ và mart parity'},
  {token:'/predict',command:'predict',label:'Pinned BTC/ETH daily forecast · no LLM',hint:'/predict BTC'},
  // Production-disabled; retain this definition for easy, deliberate reactivation.
  // {token:'/anomaly',command:'anomaly',label:'Hourly + daily Isolation Forest · no LLM',hint:'/anomaly ETH'},
  // Production-disabled with legacy model_health artifacts; implementation is retained offline.
  // {token:'/drift',command:'drift',label:'Feature PSI · no LLM',hint:'/drift BTC'},
  {token:'/tools',command:'tools',label:'List commands and code guides · no LLM',hint:'/tools'},
];
export function parseDeskInput(text, selectedSymbol='BTC') {
  const message=text.trim();
  // Plain text goes to the Analyst agent, which answers market questions itself and delegates warehouse/SRE ones.
  if (!/^[\/@]/.test(message)) return {kind:'command',command:'trade',question:message,
    symbol:['BTC','ETH','SOL'].includes(selectedSymbol)?selectedSymbol:'BTC'};
  const [token,...rest]=message.split(/\s+/);
  // @ asks an agent (an LLM picks tools); / runs one tool directly with no LLM.
  const definition=deskCommands.find(c=>c.token===token.toLowerCase());
  if (['/trade','/sre'].includes(token.toLowerCase())) throw new Error(`Agents use @: try @${token.slice(1).toLowerCase()}. / runs a tool directly.`);
  if (!definition) throw new Error('Unknown command. Agents: @trade, @sre. Tools: /predict, /tools.');
  const tail=rest.join(' ');
  if (definition.command==='tools') {
    if (tail) throw new Error('/tools takes no arguments.');
    return {kind:'tools'};
  }
  if (['trade','sre'].includes(definition.command)) {
    if (!tail) throw new Error(`Add a question after ${definition.token}.`);
    if (selectedSymbol && !['BTC','ETH','SOL'].includes(selectedSymbol)) throw new Error('Select BTC, ETH or SOL before asking an agent.');
    return {kind:'command',command:definition.command,question:tail,symbol:selectedSymbol||'BTC'};
  }
  if (rest.length>1 || (tail && !/^(BTC|ETH|SOL)$/i.test(tail))) throw new Error(`Use ${definition.token} BTC or ETH.`);
  const symbol=(tail||selectedSymbol||'BTC').toUpperCase();
  if (definition.command==='predict' && !['BTC','ETH'].includes(symbol))
    throw new Error('Predict supports BTC or ETH only.');
  return {kind:'command',command:definition.command,question:'',symbol};
}
export function toolHelp() {
  const line=c=>`- **\`${c.token}\`** — ${c.label}. Example: \`${c.hint}\``;
  return '**Ask an agent with @** (an LLM reads your question and picks tools)\n\n'+deskCommands.filter(c=>c.token.startsWith('@')).map(line).join('\n')+
    '\n\n**Run a tool with /** (no LLM, instant, works when models are busy)\n\n'+deskCommands.filter(c=>c.token.startsWith('/')).map(line).join('\n')+
    '\n\nPlain text goes to the Analyst, which hands warehouse or service questions to Operations.\n\n[Read the code](/docs/code-guide) · [Contracts](/docs/agent-contracts) · [Control guide](/docs/agent-control)';
}
