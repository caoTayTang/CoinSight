// Logos: cryptocurrency-icons 0.18.1 (CC0) and @web3icons/core 4.0.40 (MIT, NEAR and SHIB), in public/coins.
export const COIN_NAMES = {
  ADA: 'Cardano', ATOM: 'Cosmos', AVAX: 'Avalanche', BCH: 'Bitcoin Cash', BNB: 'BNB', BTC: 'Bitcoin',
  DOGE: 'Dogecoin', DOT: 'Polkadot', ETC: 'Ethereum Classic', ETH: 'Ethereum', FIL: 'Filecoin',
  LINK: 'Chainlink', LTC: 'Litecoin', NEAR: 'NEAR Protocol', SHIB: 'Shiba Inu', SOL: 'Solana', TRX: 'TRON',
  UNI: 'Uniswap', XLM: 'Stellar', XRP: 'XRP',
};

export const coinName = (symbol, name) => (name && name !== symbol ? name : COIN_NAMES[symbol]) || symbol;

export function CoinLogo({symbol, size = 28}) {
  const known = Object.hasOwn(COIN_NAMES, symbol);
  return known
    ? <img className="coin-logo" src={`/coins/${symbol.toLowerCase()}.svg`} width={size} height={size} alt="" loading="lazy"/>
    : <span className="coin-logo coin-logo-fallback" style={{width: size, height: size}} aria-hidden="true">{symbol?.[0]}</span>;
}
