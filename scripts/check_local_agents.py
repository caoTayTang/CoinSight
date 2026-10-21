"""Exercise deployed MCP -> A2A prediction -> A2A anomaly, plus direct anomaly tool."""
import argparse,asyncio,json
from pathlib import Path
from mcp import Client


async def run(url,output):
    async with Client(url,read_timeout_seconds=90) as client:
        catalog=await client.list_tools();names=[t.name for t in catalog.tools]
        assert {'predict_hourly','detect_btc_anomalies'}<=set(names)
        forecast=await client.call_tool('predict_hourly',{})
        if forecast.is_error:raise RuntimeError(str(forecast.content))
        result=forecast.structured_content
        assert result['task_id'] and result['result']['anomaly_task_id']
        value=result['result'];assert value['cutoff']==value['anomaly']['cutoff']
        assert value['inference_backend']=='verified_catboost_python_export'
        assert len(value['snapshot_sha256'])==64 and len(value['anomaly']['context_sha256'])==64
        anomaly=await client.call_tool('detect_btc_anomalies',{'cutoff':value['cutoff']})
        if anomaly.is_error:raise RuntimeError(str(anomaly.content))
        assert anomaly.structured_content['result']['context_sha256']==value['anomaly']['context_sha256']
        invalid=await client.call_tool('predict_hourly',{'cutoff':'2099-01-01T00:00:00Z'})
        assert invalid.is_error
        proof=dict(mcp_tools=names,prediction=forecast.structured_content,direct_anomaly=anomaly.structured_content,
                   future_cutoff_rejected=True,flow='MCP -> prediction A2A task -> anomaly A2A task',no_training=True)
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(proof,indent=2))
        print(json.dumps(dict(url=url,tools=names,cutoff=value['cutoff'],predicted_log_return=value['predicted_log_return'],
            prediction_task_id=result['task_id'],anomaly_task_id=value['anomaly_task_id'],is_anomaly=value['anomaly']['is_anomaly'],future_cutoff_rejected=True,proof=str(output)),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:8010/mcp')
    p.add_argument('--output',type=Path,default=Path('data/models/local-agent-runtime/smoke.json'))
    args=p.parse_args();asyncio.run(run(args.url,args.output))
