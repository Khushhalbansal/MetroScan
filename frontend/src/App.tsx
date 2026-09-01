/*
  The rail and the bench.

  A slim graphite rail carries navigation as engraved labels, the active item marked
  by a brass hairline. Everything else is the bench: bone ground, wide gutters,
  content examined under good light.
*/

import { useEffect, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import { ApiError, api, storedToken } from "./api/client";
import type { User } from "./api/types";
import { Dashboard } from "./routes/Dashboard";
import { Examination } from "./routes/Examination";
import { NewScan } from "./routes/NewScan";
import { Repository } from "./routes/Repository";
import { SignIn } from "./routes/SignIn";
import "./App.css";

type Session = { state: "loading" } | { state: "out" } | { state: "in"; user: User };

function Rail({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const items = [
    { to: "/dashboard", label: "Overview", hint: "Where enforcement stands" },
    { to: "/scans", label: "Repository", hint: "Every scan on file" },
    { to: "/scans/new", label: "New check", hint: "Photograph a package" },
  ];

  return (
    <nav className="rail" aria-label="Sections">
      <div className="rail__mark">
        <span className="rail__wordmark">MetroScan</span>
        <span className="rail__sub eyebrow">Compliance bench</span>
      </div>

      <ul className="rail__items">
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === "/scans"}
              className={({ isActive }) => `rail__link ${isActive ? "is-active" : ""}`}
            >
              <span className="rail__label">{item.label}</span>
              <span className="rail__hint">{item.hint}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="rail__foot">
        <p className="rail__who">
          <span className="rail__name">{user.full_name}</span>
          <span className="rail__role eyebrow">{user.role.replace("_", " ")}</span>
        </p>
        <button type="button" className="rail__signout" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </nav>
  );
}

export default function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!storedToken()) {
      setSession({ state: "out" });
      return;
    }
    api
      .me()
      .then((user) => setSession({ state: "in", user }))
      .catch((error: unknown) => {
        // A lapsed or revoked token is not an error to show; it is a sign-in prompt.
        if (error instanceof ApiError && (error.isUnauthenticated || error.status === 403)) {
          api.signOut();
        }
        setSession({ state: "out" });
      });
  }, []);

  const signOut = () => {
    api.signOut();
    setSession({ state: "out" });
    navigate("/sign-in");
  };

  if (session.state === "loading") {
    return (
      <main className="boot">
        <p className="boot__text eyebrow">Opening the bench</p>
      </main>
    );
  }

  if (session.state === "out") {
    return (
      <Routes>
        <Route
          path="/sign-in"
          element={<SignIn onSignedIn={(user) => setSession({ state: "in", user })} />}
        />
        <Route path="*" element={<Navigate to="/sign-in" replace />} />
      </Routes>
    );
  }

  return (
    <div className="shell">
      <Rail user={session.user} onSignOut={signOut} />
      <main className="bench">
        {/* Keyed on the path so each route mounts fresh and plays its short
            enter fade (.route in App.css). */}
        <div className="route" key={location.pathname}>
          <Routes location={location}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/scans" element={<Repository />} />
            <Route path="/scans/new" element={<NewScan />} />
            <Route path="/scans/:scanId" element={<Examination />} />
            {/* Someone who has just signed in is still standing on /sign-in; send
                them on rather than leaving them at a route this table has no page for. */}
            <Route path="/sign-in" element={<Navigate to="/dashboard" replace />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
