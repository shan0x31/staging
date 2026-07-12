import { useEffect, useState } from "react";
import { Reco, api } from "../api";
import { SeverityBadge } from "../components";

const ORDER = { action: 0, warning: 1, info: 2 } as const;

export default function Recommendations() {
  const [recos, setRecos] = useState<Reco[] | null>(null);
  const [disclaimer, setDisclaimer] = useState(
    "Rule-generated informational signals — not investment advice.");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function reload() {
    api.get<Reco[]>("/recommendations").then(setRecos).catch((e) => setError(e.message));
  }
  useEffect(reload, []);

  async function runNow() {
    setBusy(true);
    setError("");
    try {
      const r = await api.post<{ generated: number; disclaimer: string }>("/recommendations/run");
      setDisclaimer(r.disclaimer);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const sorted = (recos ?? []).slice().sort(
    (a, b) => ORDER[a.severity] - ORDER[b.severity]);

  return (
    <div>
      <h2>Recommendations</h2>
      <div className="toolbar">
        <button onClick={runNow} disabled={busy}>{busy ? "Running…" : "Run analysis now"}</button>
        <span className="hint">Also runs automatically every Sunday 18:00 IST.</span>
      </div>
      {error && <div className="error">{error}</div>}
      {recos !== null && sorted.length === 0 && (
        <div className="card hint">
          No findings in the latest run. Run the analysis after importing
          transactions and refreshing market data.
        </div>
      )}
      {sorted.map((r) => (
        <div className="card" key={r.id}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <SeverityBadge severity={r.severity} />
            {r.symbol && <b>{r.symbol}</b>}
            <span className="hint">{r.category}</span>
            <span style={{ flex: 1 }} />
            <button className="ghost small" onClick={async () => {
              await api.post(`/recommendations/${r.id}/dismiss`);
              reload();
            }}>Dismiss</button>
          </div>
          <p style={{ margin: "10px 0 4px", fontWeight: 600 }}>{r.title}</p>
          <p style={{ margin: 0, color: "var(--ink-2)" }}>{r.rationale}</p>
        </div>
      ))}
      <div className="disclaimer">{disclaimer}</div>
    </div>
  );
}
