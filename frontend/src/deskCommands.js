export const deskCommands = [
  {token:'@trade',command:'trade',label:'Market reasoning',hint:'@trade phân tích BTC và kiểm tra anomaly'},
  {token:'@sre',command:'sre',label:'Warehouse / service investigation',hint:'@sre kiểm coverage BTC 24 giờ và mart parity'},
  {token:'/predict',command:'predict',label:'Frozen BTC hourly forecast · no LLM',hint:'/predict BTC'},
  {token:'/anomaly',command:'anomaly',label:'Isolation Forest + MAD · no LLM',hint:'/anomaly BTC'},
  {token:'/drift',command:'drift',label:'Feature PSI · no LLM',hint:'/drift BTC'},
  {token:'/tools',command:'tools',label:'List commands and code guides · no LLM',hint:'/tools'},
];
export function parseDeskInput(text, selectedSymbol='BTC') {
  const message=text.trim();
  // Plain text goes to the Analyst agent, which answers market questions itself and delegates warehouse/SRE ones.
  if (!/^[\/@]/.test(message)) return {kind:'command',command:'trade',question:message,
    symbol:['BTC','ETH','SOL'].includes(selectedSymbol)?selectedSymbol:'BTC'};
  const [token,...rest]=message.split(/\s+/);
  const definition=deskCommands.find(c=>c.token===token.toLowerCase()) ||
    ({'/trade':deskCommands[0],'/sre':deskCommands[1]})[token.toLowerCase()];
  if (!definition) throw new Error('Unknown command. Use @trade, @sre, /predict, /anomaly, /drift or /tools.');
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
  if (rest.length>1 || (tail && !/^(BTC|ETH|SOL)$/i.test(tail))) throw new Error(`Use ${definition.token} BTC.`);
  const symbol=(tail||selectedSymbol||'BTC').toUpperCase();
  if (symbol!=='BTC') throw new Error('This ML tool supports BTC only. Specify BTC explicitly.');
  return {kind:'command',command:definition.command,question:'',symbol};
}
export function toolHelp() {
  return '**Desk commands**\n\n'+deskCommands.map(c=>`- **\`${c.token}\`** — ${c.label}. Example: \`${c.hint}\``).join('\n')+
    '\n\n`@trade` → Analyst; `@sre` → Operations. These agents use the model router. Direct ML commands do not call an LLM. Plain text goes to the Analyst, which picks tools and hands warehouse or SRE questions to Operations.\n\n[Read the code](/docs/code-guide) · [Contracts](/docs/agent-contracts) · [Control guide](/docs/agent-control)';
}
