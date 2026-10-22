-- Clarify that this is the open time of the newest candle in the input window.
-- Fresh databases already receive the new name from 010/init; this migration
-- upgrades databases where the forecasting schema was applied previously.
do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'dw'
          and table_name = 'fact_hourly_forecast'
          and column_name = 'input_open_time'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_schema = 'dw'
          and table_name = 'fact_hourly_forecast'
          and column_name = 'latest_input_open_time'
    ) then
        alter table dw.fact_hourly_forecast
            rename column input_open_time to latest_input_open_time;
    end if;
end
$$;
