import { useEffect, useState } from "react";
import { api } from "../api";

interface AllSettings {
  privacy_mode?: boolean;
  target_allocation?: Record<string, number>;
}

export default function Settings(props: { onLocked: () => void }) {
  const [settings, setSettings] = useState<AllSettings>({});
  const [targets, setTargets] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<AllSettings>("/settings").then((s) => {
      setSettings(s);
      if (s.target_allocation) setTargets(JSON.stringify(s.target_allocation, null, 2));
    }).catch((e) => setError(e.message));
  }, []);

  async function togglePrivacy() {
    const next = !(settings.privacy_mode ?? true);
    await api.put("/settings/privacy_mode", { value: next });
    setSettings({ ...settings, privacy_mode: next });
  }

  async function saveTargets() {
    setError(""); setMsg("");
    try {
      const parsed = targets.trim() ? JSON.parse(targets) : null;
      await api.put("/settings/target_allocation", { value: parsed });
      setMsg("Target allocation saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function refreshMarket() {
    setBusy(true); setError(""); setMsg("");
    try {
      const r = await api.post<{ refreshed: number; bars_upserted: number; failures: string[] }>("/market/refresh");
      setMsg(`Refreshed ${r.refreshed} instruments, ${r.bars_upserted} new bars` +
        (r.failures.length ? `; ${r.failures.length} failed` : ""));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    await api.post("/auth/lock");
    props.onLocked();
  }

  const privacyOn = settings.privacy_mode ?? true;

  return (
    <div>
      <h2>Settings</h2>

      <div className="card">
        <h3>Claude privacy mode</h3>
        <p className="hint">
          When ON (default), Claude conversations via the MCP connector see only
          percentages, ratios and signals — never absolute amounts, quantities,
          or account numbers.
        </p>
        <button className={privacyOn ? undefined : "ghost"} onClick={togglePrivacy}>
          Privacy mode: {privacyOn ? "ON" : "OFF"}
        </button>
      </div>

      <div className="card">
        <h3>Target allocation (%)</h3>
        <p className="hint">JSON of asset class → target percent, e.g. {"{"}"equity": 60, "fd": 30, "gold": 10{"}"}.
          Drift beyond 5pp raises a rebalancing recommendation.</p>
        <textarea
          value={targets}
          onChange={(e) => setTargets(e.target.value)}
          rows={5}
          style={{ width: "100%", fontFamily: "monospace", fontSize: 13,
                   background: "var(--surface)", color: "var(--ink)",
                   border: "1px solid var(--baseline)", borderRadius: 7, padding: 10 }}
        />
        <div style={{ marginTop: 8 }}>
          <button onClick={saveTargets}>Save targets</button>
        </div>
      </div>

      <div className="card">
        <h3>Market data</h3>
        <p className="hint">Prices refresh automatically on weekdays (18:30 IST for NSE/BSE,
          17:30 ET for US). Manual refresh fetches EOD bars for every instrument.</p>
        <button className="ghost" onClick={refreshMarket} disabled={busy}>
          {busy ? "Refreshing…" : "Refresh market data now"}
        </button>
      </div>

      <div className="card">
        <h3>Security</h3>
        <p className="hint">Locking wipes the decryption key from memory; every data
          screen requires the passphrase again.</p>
        <button className="ghost" onClick={lock}>Lock vault</button>
      </div>

      {msg && <div className="ok">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
