import { useState } from "react";
import { NavLink, useMatch, useNavigate } from "react-router-dom";
import { Briefcase, CalendarClock, Moon, Pencil, Plus, Scale, Search, Settings, Sun, Trash2 } from "lucide-react";
import { useStore } from "../store";
import { cx, daysUntil } from "../lib/util";

export default function Sidebar() {
  const nav = useNavigate();
  const activeChat = useMatch("/chat/:chatId")?.params.chatId;
  const { chats, cases, deadlines, sidebarOpen, setSidebar, deleteChat, renameChat, updateCase, theme, setTheme } = useStore();
  const [q, setQ] = useState("");
  const close = () => setSidebar(false);
  const soon = deadlines.filter((d) => !d.done && daysUntil(d.date) <= 7).length;
  const list = chats
    .filter((c) => c.title.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => b.updatedAt - a.updatedAt);
  const dark = document.documentElement.dataset.theme === "dark";

  const link = ({ isActive }: { isActive: boolean }) =>
    cx("flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm", isActive ? "bg-panel font-medium shadow-sm" : "hover:bg-panel/60");

  return (
    <>
      {sidebarOpen && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={close} />}
      <aside className={cx("fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r border-line bg-sunk transition-transform md:static md:translate-x-0", sidebarOpen ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex items-center gap-2 px-4 pb-2 pt-4">
          <Scale size={20} className="text-accent" />
          <span className="font-serif text-xl font-semibold">Cicero</span>
        </div>

        <div className="space-y-1 px-3">
          <button onClick={() => { nav("/"); close(); }} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium text-accent hover:bg-panel/60">
            <Plus size={16} /> New chat
          </button>
          <NavLink to="/cases" className={link} onClick={close}><Briefcase size={16} /> Cases</NavLink>
          <NavLink to="/deadlines" className={link} onClick={close}>
            <CalendarClock size={16} /> Deadlines
            {soon > 0 && <span className="ml-auto rounded-full bg-accent px-1.5 text-[11px] text-page">{soon}</span>}
          </NavLink>
        </div>

        {cases.length > 0 && (
          <div className="mt-4 px-3">
            <p className="px-2.5 pb-1 text-xs text-muted">Active cases</p>
            {cases.filter((c) => c.status === "active").slice(0, 4).map((c) => (
              <NavLink key={c.id} to={`/cases/${c.id}`} onClick={close} className={(s) => cx(link(s), "group")}>
                <span className="flex-1 truncate">{c.title}</span>
                <button
                  type="button"
                  aria-label={`Rename case ${c.title}`}
                  title="Rename case"
                  className="rounded p-1 text-muted opacity-0 group-hover:opacity-100 hover:text-accent"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const next = prompt("Enter new case title:", c.title);
                    if (next && next.trim()) updateCase(c.id, { title: next.trim() });
                  }}
                >
                  <Pencil size={13} />
                </button>
              </NavLink>
            ))}
          </div>
        )}

        <div className="mt-4 flex min-h-0 flex-1 flex-col px-3">
          <div className="relative mb-1">
            <Search size={14} className="absolute left-2.5 top-2.5 text-muted" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search chats" className="w-full rounded-lg border border-line bg-panel py-1.5 pl-8 pr-2 text-sm outline-none focus:border-accent" />
          </div>
          <p className="px-2.5 py-1 text-xs text-muted">Recents</p>
          <div className="-mx-1 flex-1 space-y-0.5 overflow-y-auto px-1">
            {list.length === 0 && <p className="px-2.5 py-2 text-sm text-muted">No chats yet.</p>}
            {list.map((c) => (
              <NavLink key={c.id} to={`/chat/${c.id}`} onClick={close} className={(s) => cx(link(s), "group")}>
                <span className="flex-1 truncate">{c.title}</span>
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                  <button
                    type="button"
                    aria-label={`Rename chat ${c.title}`}
                    title="Rename chat"
                    className="rounded p-1 text-muted hover:text-accent"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      const next = prompt("Enter new chat title:", c.title);
                      if (next && next.trim()) renameChat(c.id, next.trim());
                    }}
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete chat ${c.title}`}
                    title="Delete chat"
                    className="rounded p-1 text-muted hover:text-bad"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      if (confirm(`Delete "${c.title}"? Associated records will be permanently removed.`)) {
                        deleteChat(c.id);
                        if (activeChat === c.id) nav("/");
                      }
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </NavLink>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-1 border-t border-line p-3">
          <NavLink to="/settings" onClick={close} className={(s) => cx(link(s), "flex-1")}><Settings size={16} /> Settings</NavLink>
          <button aria-label="Toggle theme" className="rounded-lg p-2 hover:bg-panel/60" onClick={() => setTheme(dark ? "light" : "dark")}>
            {dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </aside>
    </>
  );
}
