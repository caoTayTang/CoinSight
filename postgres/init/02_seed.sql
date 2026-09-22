insert into dim_asset (symbol, name) values
    ('BTC', 'Bitcoin'),
    ('ETH', 'Ethereum'),
    ('SOL', 'Solana')
on conflict (symbol) do nothing;

