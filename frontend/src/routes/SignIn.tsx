/*
  Signing in.

  The hero is the thing the product actually does: a measurement against a legal limit.
  So the left half of this screen is a working Measure showing a real Rule 8 shortfall —
  1.4 mm of net-quantity type against the 2.0 mm that Table I requires for a 180 cm²
  panel. It is the most characteristic thing in this subject's world, and it says what
  the bench is for before anyone has typed anything.
*/

import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { User } from "../api/types";
import { Measure } from "../components/Measure";
import "./SignIn.css";

export function SignIn({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.signIn(email, password);
      // Report the session and stop. Navigating from here ran against the
      // *unauthenticated* route table — the session state had not propagated yet — so
      // the destination matched that table's catch-all and bounced back to /sign-in,
      // which the authenticated table then bounced somewhere else again. Where a
      // signed-in officer lands is App's decision, made once the session exists.
      onSignedIn(await api.me());
    } catch (e: unknown) {
      // The server deliberately gives one message for every way a sign-in can fail;
      // repeating it verbatim keeps that property rather than guessing at a friendlier
      // one that would leak which half was wrong.
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <main className="gate">
      <section className="gate__thesis">
        <p className="eyebrow gate__eyebrow">Legal Metrology (Packaged Commodities) Rules, 2011</p>
        <h1 className="gate__headline">
          Rule 8 does not ask whether a label looks right.
          <span className="gate__headline-em"> It asks how tall the letters are.</span>
        </h1>

        <div className="gate__demo">
          <p className="gate__demo-label eyebrow">Net quantity numerals · 180 cm² panel</p>
          <Measure
            measuredMm={1.4}
            requiredMm={2.0}
            citation="Rule 8, Table I"
            panelAreaCm2={180}
          />
        </div>

        <p className="gate__body">
          MetroScan measures the declarations on a packaged commodity from photographs,
          checks them against the rules in force on the day of the scan, and hands you
          the evidence for every finding. What it cannot settle, it hands to you.
        </p>
      </section>

      <section className="gate__form-side">
        <div className="gate__mark">
          <span className="gate__wordmark">MetroScan</span>
          <span className="eyebrow gate__mark-sub">Compliance bench</span>
        </div>

        <form className="gate__form" onSubmit={submit}>
          <h2 className="gate__form-title">Sign in</h2>

          <label className="gate__label" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            className="gate__input"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />

          <label className="gate__label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            className="gate__input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && (
            <p className="gate__error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="button button--primary gate__submit" disabled={busy}>
            {busy ? "Signing in" : "Sign in"}
          </button>

          <p className="gate__aside">
            Accounts are issued by an administrator. If you do not have one, ask the
            Controller's office for your jurisdiction.
          </p>
        </form>

        <footer className="gate__foot">
          <div className="graduated" aria-hidden="true" />
          <p className="gate__foot-note">
            Findings produced here are decision support, not a legal determination.
            Anything the photographs cannot settle is returned for an officer to judge,
            never recorded as a violation.
          </p>
        </footer>
      </section>
    </main>
  );
}
