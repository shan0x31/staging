import { FormEvent, useState } from "react";
import { AuthStatus, api, setToken } from "../api";

export default function Login(props: { status: AuthStatus; onAuthed: () => void }) {
  const { status } = props;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (!status.setup_complete) {
        const r = await api.post<{ token: string }>("/auth/setup", {
          username, password, encryption_passphrase: passphrase,
        });
        setToken(r.token);
      } else {
        const r = await api.post<{ token: string }>("/auth/login", { username, password });
        setToken(r.token);
        if (!status.unlocked && passphrase) {
          await api.post("/auth/unlock", { passphrase });
        }
      }
      props.onAuthed();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="card">
        <h2>{status.setup_complete ? "Sign in" : "Create your vault"}</h2>
        {!status.setup_complete && (
          <p className="hint">
            First run. Your encryption passphrase protects all financial data at
            rest — it is never stored, and losing it makes the data unrecoverable.
          </p>
        )}
        <form onSubmit={submit}>
          <label>Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {(!status.setup_complete || !status.unlocked) && (
            <>
              <label>Encryption passphrase{status.setup_complete ? " (to unlock data)" : ""}</label>
              <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />
            </>
          )}
          <div style={{ marginTop: 16 }}>
            <button disabled={busy}>{status.setup_complete ? "Sign in" : "Create vault"}</button>
          </div>
          {error && <div className="error">{error}</div>}
        </form>
      </div>
    </div>
  );
}
