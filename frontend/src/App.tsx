import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { ApiError, AuthStatus, api, getToken, setToken } from "./api";
import Dashboard from "./pages/Dashboard";
import Holdings from "./pages/Holdings";
import Login from "./pages/Login";
import Recommendations from "./pages/Recommendations";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Transactions from "./pages/Transactions";

export default function App() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const navigate = useNavigate();

  const refreshStatus = useCallback(async () => {
    const s = await api.get<AuthStatus>("/auth/status");
    setStatus(s);
    if (getToken()) {
      try {
        await api.get("/auth/me");
        setAuthed(true);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setToken(null);
          setAuthed(false);
        }
      }
    }
    return s;
  }, []);

  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  if (status === null) return <div className="hint" style={{ padding: 40 }}>Loading…</div>;

  if (!authed || !status.setup_complete || !status.unlocked) {
    return (
      <Login
        status={status}
        onAuthed={async () => {
          await refreshStatus();
          navigate("/");
        }}
      />
    );
  }

  async function logout() {
    try { await api.post("/auth/logout"); } catch { /* session may be gone */ }
    setToken(null);
    setAuthed(false);
  }

  return (
    <div className="layout">
      <nav className="nav">
        <h1>Personal Finance</h1>
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/holdings">Holdings</NavLink>
        <NavLink to="/transactions">Transactions</NavLink>
        <NavLink to="/recommendations">Recommendations</NavLink>
        <NavLink to="/reports">Reports</NavLink>
        <NavLink to="/settings">Settings</NavLink>
        <a onClick={logout} style={{ cursor: "pointer", marginTop: 20 }}>Sign out</a>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/holdings" element={<Holdings />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/recommendations" element={<Recommendations />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings onLocked={refreshStatus} />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}
