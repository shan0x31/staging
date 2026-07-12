import { useEffect, useState } from "react";
import { Mover, Summary, api } from "../api";
import { AllocationBars, StatTile, fmtMoney } from "../components";

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [movers, setMovers] = useState<Mover[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Summary>("/portfolio/summary").then(setSummary).catch((e) => setError(e.message));
    api.get<Mover[]>("/market/movers").then(setMovers).catch(() => setMovers([]));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!summary) return <div className="hint">Loading…</div>;
  const ccy = summary.base_currency;
  const pnl = summary.unrealized_pnl;

  return (
    <div>
      <h2>Dashboard</h2>
      <div className="tiles">
        <StatTile label={`Net worth (${ccy})`} value={fmtMoney(summary.net_worth, ccy)}
          sub={summary.unpriced_instruments > 0 ? `${summary.unpriced_instruments} unpriced — refresh market data` : undefined} />
        <StatTile label="Invested" value={fmtMoney(summary.invested, ccy)} />
        <StatTile label="Unrealized P&L"
          value={<span className={pnl !== null && pnl < 0 ? "neg" : "pos"}>{fmtMoney(pnl, ccy)}</span>} />
        <StatTile label="XIRR" value={summary.xirr_pct !== null ? `${summary.xirr_pct}%` : "—"}
          sub={summary.usdinr ? `USD/INR ${summary.usdinr.toFixed(2)}` : undefined} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
        <div className="card">
          <h3>Allocation by asset class</h3>
          <AllocationBars data={summary.allocation_by_class} />
        </div>
        <div className="card">
          <h3>Allocation by currency</h3>
          <AllocationBars data={summary.allocation_by_currency} />
        </div>
        <div className="card">
          <h3>Allocation by sector</h3>
          <AllocationBars data={summary.allocation_by_sector} />
        </div>
      </div>

      <div className="card">
        <h3>Today's movers (held positions)</h3>
        {movers.length === 0 ? (
          <div className="hint">No price history yet — refresh market data from Settings.</div>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr><th>Symbol</th><th>Name</th><th className="num">Close</th><th className="num">Day change</th></tr>
              </thead>
              <tbody>
                {movers.slice(0, 10).map((m) => (
                  <tr key={m.symbol}>
                    <td>{m.symbol}</td>
                    <td>{m.name}</td>
                    <td className="num">{m.close.toLocaleString()}</td>
                    <td className={`num ${m.change_pct >= 0 ? "pos" : "neg"}`}>
                      {m.change_pct >= 0 ? "+" : ""}{m.change_pct.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
