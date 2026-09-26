import { useState, type FormEvent } from 'react';
import { login, useDB } from '../data/store';
import { ROLE_LABELS } from '../data/types';

export function Login() {
  const db = useDB();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    // Demo auth: any password for a seeded account. Production auth (bcrypt + optional TOTP 2FA) lives server-side.
    if (!password) return setError('Enter your password.');
    if (!login(email)) setError('No account found for that email.');
  };

  return (
    <div className="login">
      <form className="login-card" onSubmit={submit}>
        <div className="row">
          <img src="./icon.svg" alt="" width={40} height={40} />
          <div>
            <h1 style={{ fontSize: 20 }}>Green Media</h1>
            <p className="muted small">AI Command Center — grow every client from one dashboard</p>
          </div>
        </div>
        <label className="field">
          Email
          <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field">
          Password
          <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="notice">{error}</div>}
        <button className="btn block" type="submit">Sign in</button>
        <div>
          <p className="muted small" style={{ marginBottom: 6 }}>Demo accounts — tap to fill:</p>
          <div className="demo-users">
            {db.users.map((u) => (
              <button type="button" key={u.id} onClick={() => { setEmail(u.email); setPassword('demo'); setError(''); }}>
                <strong>{ROLE_LABELS[u.role]}</strong>
                {u.name}
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}
