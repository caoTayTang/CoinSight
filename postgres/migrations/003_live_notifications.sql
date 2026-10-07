-- Notify connected API clients only after a live write commits.
-- Repeated symbols in one Spark micro-batch become one notification per symbol.
create or replace function dw.notify_live_change() returns trigger
language plpgsql as $$
begin
    perform pg_notify('coinsight_live', new.symbol);
    return new;
end;
$$;

drop trigger if exists notify_live_candle on dw.fact_candle_minute_live;
create trigger notify_live_candle
after insert on dw.fact_candle_minute_live
for each row execute function dw.notify_live_change();

drop trigger if exists notify_live_metric on dw.fact_stream_metric_v1;
create trigger notify_live_metric
after insert or update on dw.fact_stream_metric_v1
for each row execute function dw.notify_live_change();
