import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";

// Self-hosted faces (design-direction.md notes a government deployment should not
// depend on a CDN reaching a district office). Variable files for the Latin faces,
// static 400/500/600 for Devanagari and Mono. font-display: swap is built in.
import "@fontsource-variable/archivo/wdth.css";
import "@fontsource-variable/ibm-plex-sans/wght.css";
import "@fontsource/ibm-plex-sans-devanagari/devanagari-400.css";
import "@fontsource/ibm-plex-sans-devanagari/devanagari-500.css";
import "@fontsource/ibm-plex-sans-devanagari/devanagari-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "@fontsource/ibm-plex-mono/latin-600.css";

import "./styles/tokens.css";
import "./styles/controls.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
