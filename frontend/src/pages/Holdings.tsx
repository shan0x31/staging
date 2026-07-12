import { useEffect, useState } from "react";
import { Holding, api } from "../api";
import { PnL, fmtMoney, fmtNum } from "../components";

export default function Holdings() {
  const [holdings, setHoldings] = useState<Holding[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Holding[]>("/portfolio/holdings").then(setHoldings).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!holdings) return <div className="hint">Loading…</div>;

  return (
    <div>
      <h2>Holdings</h2>
      <div className="card scroll-x">
        {holdings.length === 0 ? (
          <div className="hint">No positions yet — add transactions or import a CSV.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th><th>Name</th><th>Class</th><th>Sector</th>
                <th className="num">Qty</th><th className="num">Avg cost</th>
                <th className="num">Price</th><th className="num">Value</th>
                <th className="num">Unrealized P&L</th><th className="num">Dividends</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => (
                <tr key={h.instrument.id}>
                  <td>{h.instrument.symbol}</td>
                  <td>{h.instrument.name}</td>
                  <td>{h.instrument.asset_class}</td>
                  <td>{h.instrument.sector ?? "—"}</td>
                  <td className="num">{fmtNum(h.quantity, 4)}</td>
                  <td className="num">{fmtNum(h.avg_cost)}</td>
                  <td className="num">{h.current_price !== null ? fmtNum(h.current_price) : "—"}</td>
                  <td className="num">{fmtMoney(h.current_value, h.instrument.currency)}</td>
                  <td className="num">
                    <PnL value={h.unrealized_pnl} pct={h.unrealized_pnl_pct} ccy={h.instrument.currency} />
                  </td>
                  <td className="num">{fmtMoney(h.dividends, h.instrument.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
