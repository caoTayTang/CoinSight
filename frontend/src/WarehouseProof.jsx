import { useEffect, useState } from 'react';
import { api, amount } from './format.js';

export function WarehouseProof() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api('/v1/warehouse/proof').then((value) => { if (active) setReport(value); })
      .catch((reason) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, []);
  return <section className="warehouse-proof">
    <h3>Warehouse proof</h3>
    {error ? <p role="alert">Unable to load proof: {error}</p> : !report ? <p>Loading warehouse evidence…</p> : <>
      <p>{report.batch ? `Load #${report.batch.batch_id} · ${report.batch.status} · ${report.batch.rows_loaded ?? '—'} changed facts` : 'No warehouse load has run yet.'}</p>
      <h4>Staging → facts · latest load</h4>
      <p>Accepted = distinct valid candles. Changed = inserts or updates; unchanged facts are not rewritten.</p>
      <div className="proof-table"><table><thead><tr><th>Asset / source</th><th>Interval</th><th>Staged</th><th>Rejected</th><th>Duplicates</th><th>Accepted</th><th>Changed</th></tr></thead>
        <tbody>{report.load_report.map((row) => <tr key={`${row.symbol}:${row.source_code}:${row.candle_interval}`}>
          <td>{row.symbol} / {row.source_code}</td><td>{row.candle_interval}</td>
          {['staging_rows', 'rejected_rows', 'duplicate_rows', 'accepted_rows', 'changed_rows'].map((key) => <td key={key}>{amount(row[key], 0)}</td>)}
        </tr>)}</tbody></table></div>
      {!report.load_report.length && <p>No per-asset audit for this load. Run a new load after migration.</p>}
      <h4>Warehouse coverage</h4><p>{report.coverage_scope}</p>
      <div className="proof-table"><table><thead><tr><th>Asset / source</th><th>Interval</th><th>Facts</th><th>Expected</th><th>Missing</th><th>Duplicates</th><th>Archive evidence</th></tr></thead>
        <tbody>{report.coverage.map((row) => <tr key={`${row.symbol}:${row.source_code}:${row.candle_interval}`}>
          <td>{row.symbol} / {row.source_code}</td><td>{row.candle_interval}</td>
          {['fact_rows', 'expected_candles', 'missing_candles', 'duplicate_rows'].map((key) => <td key={key}>{amount(row[key], 0)}</td>)}
          <td><a href={`/api/v1/warehouse/lineage/${encodeURIComponent(row.symbol)}`} target="_blank" rel="noopener noreferrer">Archive / SHA-256 ↗</a></td>
        </tr>)}</tbody></table></div>
      <a href="/docs/warehouse-proof">Proof commands & limitations ↗</a>
    </>}
  </section>;
}
