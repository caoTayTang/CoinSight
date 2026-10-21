-- Remove the retired CSV replay stream mode. Live Binance candles are the only
-- supported streaming contract.
delete from dw.fact_stream_metric_v1 where mode <> 'live';

alter table dw.fact_stream_metric_v1
    drop constraint if exists fact_stream_metric_v1_mode_check;

alter table dw.fact_stream_metric_v1
    add constraint fact_stream_metric_v1_mode_check check (mode = 'live');
