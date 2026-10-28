"""Exercise deployed MCP -> A2A daily support, plus direct anomaly tool."""
import argparse,asyncio,json
from pathlib import Path
from mcp import Client


async def run(url,output):
    async with Client(url,read_timeout_seconds=90) as client:
        catalog=await client.list_tools();names=[t.name for t in catalog.tools]
        assert {'forecast_support','detect_btc_anomalies'}<=set(names)
        forecast=await client.call_tool('forecast_support',{'symbol':'BTC'})
        if forecast.is_error:raise RuntimeError(str(forecast.content))
        result=forecast.structured_content
        assert result['task_id']
        value=result['result'];assert value['status']=='ready' and value['symbol']=='BTC'
        assert value['forecast']['return_q10']<=value['forecast']['return_q50']<=value['forecast']['return_q90']
        assert value['recent_performance']['causal'] is True
        anomaly=await client.call_tool('detect_btc_anomalies',{})
        if anomaly.is_error:raise RuntimeError(str(anomaly.content))
        invalid=await client.call_tool('forecast_support',{'cutoff':'2099-01-01T00:00:00Z'})
        assert not invalid.is_error and invalid.structured_content['result']['status']=='unavailable'
        proof=dict(mcp_tools=names,prediction=forecast.structured_content,direct_anomaly=anomaly.structured_content,
                   future_cutoff_rejected=True,flow='MCP -> daily support A2A task',no_training=True)
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(proof,indent=2))
        print(json.dumps(dict(url=url,tools=names,target_close=value['forecast']['target_close'],
            q50=value['forecast']['return_q50'],prediction_task_id=result['task_id'],
            future_cutoff_rejected=True,proof=str(output)),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:8010/mcp')
    p.add_argument('--output',type=Path,default=Path('data/models/local-agent-runtime/smoke.json'))
    args=p.parse_args();asyncio.run(run(args.url,args.output))
