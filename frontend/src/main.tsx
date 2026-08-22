import React from "react";
import ReactDOM from "react-dom/client";

import App from "@/App";
import "@/index.css";
import { initTheme } from "@/lib/theme";

initTheme();

// Register the service worker AFTER load, so it never competes with the first paint for
// bandwidth. Guarded on the API existing and on production: in dev a cached shell would serve
// yesterday's bundle over the top of a live rebuild, which is maddening to debug.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      // Registration failing must never take the app down with it - the site works perfectly
      // well without offline support, it just is not installable.
      console.warn("service worker registration failed:", err);
    });
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
