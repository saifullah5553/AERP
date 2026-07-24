import { HashRouter, Route, Routes } from "react-router-dom";

import CompanyPage from "@/features/company/CompanyPage";
import ScreenerPage from "@/features/screener/ScreenerPage";

// HashRouter keeps deep links working on GitHub Pages (no server-side rewrites),
// and is harmless behind a real backend.
export default function App() {
  return (
    <div className="h-screen w-screen overflow-hidden bg-base-900">
      <HashRouter>
        <Routes>
          <Route path="/" element={<ScreenerPage />} />
          <Route path="/company/:symbol" element={<CompanyPage />} />
        </Routes>
      </HashRouter>
    </div>
  );
}
