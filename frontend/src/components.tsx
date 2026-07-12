import { ReactNode } from "react";

// Fixed slot order from the validated palette; color follows the entity.
const SLOTS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
const CLASS_SLOTS: Record<string, string> = {
  equity: "--s1", mutual_fund: "--s2", etf: "--s3", gold: "--s4",
  fd: "--s5", cash: "--s6", real_estate: "--s7", crypto: "--s8",
  bond: "--s5", epf: "--s5", ppf: "--s5", other: "--s8",
  INR: "--s1", USD: "--s2",
};

export function slotFor(name: string, index: number): string {
  return CLASS_SLOTS[name] ?? SLOTS[index % SLOTS.length];
}

export function StatTile(props: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="tile">
      <div className="label">{props.label}</div>
      <div className="value">{props.value}</div>
      {props.sub !== undefined && <div className="sub">{props.sub}</div>}
    </div>
  );
}

export function AllocationBars(props: { data: Record<string, number> }) {
  const entries = Object.entries(props.data).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return <div className="hint">No priced positions yet.</div>;
  // stable slot per entity: rank within alphabetical order for unknown names
  const alpha = [...Object.keys(props.data)].sort();
  return (
    <div>
      {entries.map(([name, pct]) => (
        <div className="alloc-row" key={name}>
          <div className="name" title={name}>{name}</div>
          <div className="alloc-track">
            <div
              className="alloc-fill"
              style={{ width: `${Math.min(pct, 100)}%`, background: `var(${slotFor(name, alpha.indexOf(name))})` }}
            />
          </div>
          <div className="pct">{pct.toFixed(1)}%</div>
        </div>
      ))}
    </div>
  );
}

const SEVERITY: Record<string, { var: string; icon: string; label: string }> = {
  info: { var: "--muted", icon: "ℹ", label: "Info" },
  warning: { var: "--status-warning", icon: "▲", label: "Warning" },
  action: { var: "--status-serious", icon: "●", label: "Action" },
};

export function SeverityBadge({ severity }: { severity: string }) {
  const s = SEVERITY[severity] ?? SEVERITY.info;
  return (
    <span className="badge">
      <span className="dot" style={{ background: `var(${s.var})` }} />
      {s.icon} {s.label}
    </span>
  );
}

export function fmtMoney(v: number | null | undefined, ccy = "INR"): string {
  if (v === null || v === undefined) return "—";
  const locale = ccy === "INR" ? "en-IN" : "en-US";
  return new Intl.NumberFormat(locale, {
    style: "currency", currency: ccy, maximumFractionDigits: 0,
  }).format(v);
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function PnL({ value, pct, ccy }: { value: number | null; pct?: number | null; ccy?: string }) {
  if (value === null) return <>—</>;
  const cls = value >= 0 ? "pos" : "neg";
  return (
    <span className={cls}>
      {fmtMoney(value, ccy)}{pct !== undefined && pct !== null && ` (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`}
    </span>
  );
}
