import { ChangeEvent, useEffect, useRef, useState } from "react";
import { Account, ImportSummary, Instrument, Txn, api } from "../api";

const TEMPLATE = "date,type,symbol,name,exchange,asset_class,quantity,price,fees,amount,currency,account,notes\n" +
  "2024-01-10,buy,RELIANCE.NS,Reliance Industries,NSE,equity,10,2450.50,20,,INR,Zerodha,\n" +
  "2024-02-15,buy,AAPL,Apple Inc,NASDAQ,equity,5,182.30,1,,USD,Fidelity,\n" +
  "2024-03-01,dividend,RELIANCE.NS,,,,,,,90.00,INR,Zerodha,\n";

export default function Transactions() {
  const [txns, setTxns] = useState<Txn[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [importResult, setImportResult] = useState<ImportSummary | null>(null);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  function reload() {
    api.get<Txn[]>("/transactions").then(setTxns).catch((e) => setError(e.message));
    api.get<Account[]>("/accounts").then(setAccounts).catch(() => {});
    api.get<Instrument[]>("/instruments").then(setInstruments).catch(() => {});
  }
  useEffect(reload, []);

  async function onUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    try {
      const result = await api.upload<ImportSummary>("/transactions/import", file);
      setImportResult(result);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      e.target.value = "";
    }
  }

  function downloadTemplate() {
    const blob = new Blob([TEMPLATE], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "import-template.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const acctName = (id: number) => accounts.find((a) => a.id === id)?.name ?? id;
  const instSymbol = (id: number | null) =>
    id === null ? "—" : instruments.find((i) => i.id === id)?.symbol ?? id;

  return (
    <div>
      <h2>Transactions</h2>
      <div className="toolbar">
        <input ref={fileInput} type="file" accept=".csv" onChange={onUpload} style={{ display: "none" }} />
        <button className="ghost" onClick={() => fileInput.current?.click()}>Import CSV</button>
        <button className="ghost" onClick={downloadTemplate}>Download template</button>
        <span className="hint">
          Auto-detects Zerodha tradebook, Groww tradebook, and US-broker activity
          CSVs, plus the generic template.
        </span>
      </div>
      {importResult && (
        <div className="card">
          <b>Import result</b> ({importResult.detected_format} format):{" "}
          {importResult.imported} imported,{" "}
          {importResult.skipped_duplicates} duplicates skipped
          {importResult.errors.length > 0 && (
            <ul>{importResult.errors.map((e, i) => <li key={i} className="error">{e}</li>)}</ul>
          )}
        </div>
      )}
      {error && <div className="error">{error}</div>}
      <div className="card scroll-x">
        {txns.length === 0 ? (
          <div className="hint">No transactions yet. Import a CSV to get started.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th><th>Type</th><th>Symbol</th><th>Account</th>
                <th className="num">Qty</th><th className="num">Price</th>
                <th className="num">Amount</th><th></th>
              </tr>
            </thead>
            <tbody>
              {txns.map((t) => (
                <tr key={t.id}>
                  <td>{t.trade_date}</td>
                  <td>{t.type}</td>
                  <td>{instSymbol(t.instrument_id)}</td>
                  <td>{acctName(t.account_id)}</td>
                  <td className="num">{t.quantity ?? "—"}</td>
                  <td className="num">{t.price ?? "—"}</td>
                  <td className="num">{t.amount ?? "—"}</td>
                  <td>
                    <button className="ghost small" onClick={async () => {
                      await api.del(`/transactions/${t.id}`);
                      reload();
                    }}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
