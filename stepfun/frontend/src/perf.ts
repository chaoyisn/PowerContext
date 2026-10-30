export type PerfRecord = {
  at: string;
  name: string;
  [key: string]: string | number | boolean | undefined;
};

const key = "edgeseek.performance.v1";

export function recordPerf(name: string, fields: Record<string, string | number | boolean | undefined> = {}) {
  const records = readPerf();
  records.push({ at: new Date().toISOString(), name, ...fields });
  localStorage.setItem(key, JSON.stringify(records.slice(-2000)));
  window.dispatchEvent(new Event("edgeseek:performance"));
}

export function readPerf(): PerfRecord[] {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "[]") as PerfRecord[];
  } catch {
    return [];
  }
}

export function downloadPerf(format: "json" | "csv") {
  const records = readPerf();
  const columns = [...new Set(records.flatMap((row) => Object.keys(row)))];
  const content = format === "json"
    ? JSON.stringify(records, null, 2)
    : [columns.join(","), ...records.map((row) => columns.map((column) => csvCell(row[column])).join(","))].join("\n");
  const blob = new Blob([content], { type: format === "json" ? "application/json" : "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `edgeseek-performance.${format}`;
  link.click();
  URL.revokeObjectURL(url);
}

function csvCell(value: unknown) {
  const text = value == null ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}
