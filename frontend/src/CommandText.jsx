import {commandFor, splitCommands} from './commandTokens.js';

export function CommandChip({token, onCommand}) {
  const command = commandFor(token);
  if (!command) return token;
  // Without a composer (admin console) the chip is bold text with the same hint.
  if (!onCommand) return <strong className="command-chip" title={command.label}>{token}</strong>;
  return <button type="button" className="command-chip" title={`${command.label} · click to use`}
    onClick={() => onCommand(command.token)}>{token}</button>;
}

export function CommandText({text, onCommand}) {
  return splitCommands(text).map((part, i) =>
    typeof part === 'string' ? part : <CommandChip key={i} token={part.token} onCommand={onCommand}/>);
}

// Same text behind the textarea, with real tokens highlighted. Highlights only: no bold or padding, so the
// glyphs stay exactly under the textarea's own text.
export function ComposerBackdrop({text, backdropRef}) {
  return <div className="composer-backdrop" ref={backdropRef} aria-hidden="true">
    {splitCommands(text).map((part, i) => typeof part === 'string' ? part : <mark key={i}>{part.token}</mark>)}
    {'\n'}
  </div>;
}
