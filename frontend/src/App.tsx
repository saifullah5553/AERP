import { BrowserRouter, Route, Routes } from "react-router-dom";

import CompanyPage from "@/features/company/CompanyPage";
import ScreenerPage from "@/features/screener/ScreenerPage";

export default function App() {
  return (
    <div className="h-screen w-screen overflow-hidden bg-base-900">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ScreenerPage />} />
          <Route path="/company/:symbol" element={<CompanyPage />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}
