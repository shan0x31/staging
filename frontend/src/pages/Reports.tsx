import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { StatTile, fmtMoney } from "../components";

interface GainRecord {
  symbol: string; quantity: number; acquire_date: string; sell_date: string;
  holding_days: number; term: "short" | "long"; cost: number; proceeds: number; gain: number;
}
interface GainsReport {
  period: string; currency: string; short_term_gain: number; long_term_gain: number;
  total_proceeds: number; sale_count: number; records: GainRecord[];
  ltcg_exemption_inr?: number; ltcg_above_exemption?: number; disclaimer: string;
}
interface DividendReport {
  period: string; currency: string; total: number;
  by_instrument: { symbol: string; total: number; count: number }[];
}
interface Periods { fy_in: number[]; calendar_us: number[] }

export default function Reports() {
  const [periods, setPeriods] = useState<Periods>({ fy_in: [], calendar_us: [] });
  const [basis, setBasis] = useState<"fy_in" | "calendar_us">("fy_in");
  const [year, setYear] = useState<number | null>(null);
  const [gains, setGains] = useState<GainsReport | null>(null);
  const [dividends, setDividends] = useState<DividendReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Periods>("/reports/periods").then((p) => {
      setPeriods(p);
      if (p.fy_in.length) setYear(p.fy_in[0]);
    }).catch((e) => setError(e.message));
  }, []);

  const load = useCallback(() => {
    if (year === null) return;
    setError("");
    api.get<GainsReport>(`/reports/capital-gains?year=${year}&basis=${basis}`)
      .then(setGains).catch((e) => setError(e.message));
    api.get<DividendReport>(`/reports/dividends?year=${year}&basis=${basis}`)
      .then(setDividends).catch(() => setDividends(null));
  }, [year, basis]);
  useEffect(load, [load]);

  const options = basis === "fy_in" ? periods.fy_in : periods.calendar_us;
  const ccy = gains?.currency ?? "INR";

  return (
    <div>
      <h2>Tax reports</h2>
      <div className="toolbar">
        <select value={basis} style={{ width: "auto" }} onChange={(e) => {
          const b = e.target.value as "fy_in" | "calendar_us";
          setBasis(b);
          const opts = b === "fy_in" ? periods.fy_in : periods.calendar_us;
          setYear(opts[0] ?? null);
        }}>
          <option value="fy_in">India — financial year</option>
          <option value="calendar_us">US — calendar year</option>
        </select>
        <select value={year ?? ""} style={{ width: "auto" }}
                onChange={(e) => setYear(Number(e.target.value))}>
          {options.map((y) => (
            <option key={y} value={y}>
              {basis === "fy_in" ? `FY${y}-${String(y + 1).slice(-2)}` : y}
            </option>
          ))}
        </select>
      </div>
      {error && <div className="error">{error}</div>}
      {year === null && <div className="card hint">No transactions yet — reports appear once your ledger has activity.</div>}

      {gains && (
        <>
          <div className="tiles">
            <StatTile label="Short-term gains" value={fmtMoney(gains.short_term_gain, ccy)} />
            <StatTile label="Long-term gains" value={fmtMoney(gains.long_term_gain, ccy)}
              sub={gains.ltcg_exemption_inr !== undefined
                ? `Above ₹${(gains.ltcg_exemption_inr / 1000).toFixed(0)}k exemption: ${fmtMoney(gains.ltcg_above_exemption ?? 0, ccy)}`
                : undefined} />
            <StatTile label="Total proceeds" value={fmtMoney(gains.total_proceeds, ccy)}
              sub={`${gains.sale_count} lot sales`} />
            <StatTile label="Dividends" value={fmtMoney(dividends?.total ?? null, ccy)} />
          </div>

          <div className="card scroll-x">
            <h3>Realized lot sales — {gains.period}</h3>
            {gains.records.length === 0 ? (
              <div className="hint">No sales in this period.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th><th>Acquired</th><th>Sold</th>
                    <th className="num">Days held</th><th>Term</th>
                    <th className="num">Qty</th><th className="num">Cost</th>
                    <th className="num">Proceeds</th><th className="num">Gain</th>
                  </tr>
                </thead>
                <tbody>
                  {gains.records.map((r, i) => (
                    <tr key={i}>
                      <td>{r.symbol}</td>
                      <td>{r.acquire_date}</td>
                      <td>{r.sell_date}</td>
                      <td className="num">{r.holding_days}</td>
                      <td>{r.term === "long" ? "Long" : "Short"}</td>
                      <td className="num">{r.quantity}</td>
                      <td className="num">{fmtMoney(r.cost, ccy)}</td>
                      <td className="num">{fmtMoney(r.proceeds, ccy)}</td>
                      <td className={`num ${r.gain >= 0 ? "pos" : "neg"}`}>{fmtMoney(r.gain, ccy)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {dividends && dividends.by_instrument.length > 0 && (
            <div className="card scroll-x">
              <h3>Dividend income — {dividends.period}</h3>
              <table>
                <thead>
                  <tr><th>Symbol</th><th className="num">Payments</th><th className="num">Total</th></tr>
                </thead>
                <tbody>
                  {dividends.by_instrument.map((d) => (
                    <tr key={d.symbol}>
                      <td>{d.symbol}</td>
                      <td className="num">{d.count}</td>
                      <td className="num">{fmtMoney(d.total, ccy)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="disclaimer">{gains.disclaimer}</div>
        </>
      )}
    </div>
  );
}
