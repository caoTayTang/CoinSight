-- Reference data for tracked assets. Unknown symbols found by the batch ETL or
-- the stream are added with their symbol as name and no category.

insert into dw.dim_asset (symbol, name, category, is_stablecoin) values
    ('BTC', 'Bitcoin', 'layer-1', false),
    ('ETH', 'Ethereum', 'layer-1', false),
    ('BNB', 'BNB', 'exchange', false),
    ('SOL', 'Solana', 'layer-1', false),
    ('XRP', 'XRP', 'payments', false),
    ('ADA', 'Cardano', 'layer-1', false),
    ('DOGE', 'Dogecoin', 'meme', false),
    ('TRX', 'TRON', 'layer-1', false),
    ('AVAX', 'Avalanche', 'layer-1', false),
    ('LINK', 'Chainlink', 'oracle', false),
    ('DOT', 'Polkadot', 'layer-1', false),
    ('LTC', 'Litecoin', 'payments', false),
    ('BCH', 'Bitcoin Cash', 'payments', false),
    ('UNI', 'Uniswap', 'defi', false),
    ('ATOM', 'Cosmos', 'layer-1', false),
    ('XLM', 'Stellar', 'payments', false),
    ('ETC', 'Ethereum Classic', 'layer-1', false),
    ('FIL', 'Filecoin', 'storage', false),
    ('NEAR', 'NEAR Protocol', 'layer-1', false),
    ('SHIB', 'Shiba Inu', 'meme', false)
on conflict (symbol) do update set
    name = excluded.name,
    category = excluded.category,
    is_stablecoin = excluded.is_stablecoin,
    updated_at = now();
