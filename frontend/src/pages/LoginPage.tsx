import { FormEvent, useState } from "react";
import { Field } from "../components/ui";
import { useAuth } from "../store/authStore";

export default function LoginPage() {
  const { phase, appName, login, setup } = useAuth();
  const isSetup = phase === "setup";
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (isSetup) await setup(email, name, password);
      else await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-screen">
      <form className="card auth-card" onSubmit={submit}>
        <div className="brand brand-lg">
          <svg viewBox="0 0 32 32" width="32" height="32" aria-hidden="true"><path d="M4 6h24l-9 11v8l-6 3V17z" fill="currentColor" /></svg>
          <span>{appName}</span>
        </div>
        <h1>{isSetup ? "Create your owner account" : "Sign in"}</h1>
        {isSetup && <p className="muted">First run: this account will own the CRM. You can change the password later in Settings.</p>}
        <Field label="Email"><input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        {isSetup && <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>}
        <Field label="Password" hint={isSetup ? "At least 8 characters" : undefined}>
          <input type="password" required minLength={isSetup ? 8 : 1} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <div className="error-box">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Please wait…" : isSetup ? "Create account" : "Sign in"}</button>
      </form>
    </div>
  );
}
