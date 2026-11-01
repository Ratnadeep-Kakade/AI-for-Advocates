export const uid = (): string =>
  globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36);

export const cx = (...a: (string | false | null | undefined)[]): string => a.filter(Boolean).join(" ");

export const fmtDate = (d: number | string): string =>
  new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

export const fmtTime = (d: number): string =>
  new Date(d).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export const fmtSize = (n: number): string =>
  n < 1024 ? `${n} B` : n < 1048576 ? `${Math.round(n / 1024)} KB` : `${(n / 1048576).toFixed(1)} MB`;

export function daysUntil(date: string): number {
  const d = new Date(date + "T00:00:00");
  const t = new Date();
  t.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - t.getTime()) / 86400000);
}

export function download(filename: string, text: string, type = "text/markdown") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
