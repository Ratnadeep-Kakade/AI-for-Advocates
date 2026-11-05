import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useStore } from "./store";
import { USE_MOCK, fetchModels } from "./lib/api";
import Sidebar from "./components/Sidebar";
import ChatPage from "./pages/ChatPage";
import CasesPage from "./pages/CasesPage";
import CaseWorkspace from "./pages/CaseWorkspace";
import DeadlinesPage from "./pages/DeadlinesPage";
import SettingsPage from "./pages/SettingsPage";

function Layout() {
  const theme = useStore((s) => s.theme);
  const setModels = useStore((s) => s.setModels);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = theme === "dark" || (theme === "system" && mq.matches) ? "dark" : "light";
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme]);

  useEffect(() => { fetchModels().then(setModels); }, [setModels]);

  return (
    <div className="flex h-dvh flex-col">
      {USE_MOCK && (
        <div className="shrink-0 bg-accent-soft px-4 py-1.5 text-center text-xs text-accent">
          Demo mode: answers and sources are sample data, not legal authority.
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col"><Outlet /></main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ChatPage />} />
        <Route path="chat/:chatId" element={<ChatPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:caseId" element={<CaseWorkspace />} />
        <Route path="deadlines" element={<DeadlinesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
