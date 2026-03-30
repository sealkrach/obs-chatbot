import React, { useEffect, useState } from "react";
import { Activity, X, Check, Loader2, RefreshCw, Play, Pause } from "lucide-react";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8001";

interface CollectorConfig {
  enabled: boolean;
  interval_seconds: number;
  metrics: Record<string, boolean>;
}

interface StoreStats {
  total_points: number;
  max_capacity: number;
  metrics: string[];
  oldest_ns: number | null;
  newest_ns: number | null;
}

const METRIC_LABELS: Record<string, string> = {
  cpu: "CPU (utilisation, fréquence, par cœur)",
  memory: "Mémoire (RAM, swap)",
  disk: "Disque (utilisation, I/O par partition)",
  network: "Réseau (octets, paquets, erreurs)",
  processes: "Processus (nombre, top CPU/RAM)",
  battery: "Batterie (niveau, branché)",
  load_avg: "Charge système (1/5/15 min)",
};

export default function CollectorConfigPanel() {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<CollectorConfig | null>(null);
  const [stats, setStats] = useState<StoreStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [collecting, setCollecting] = useState(false);

  // Form
  const [enabled, setEnabled] = useState(false);
  const [interval, setInterval_] = useState(15);
  const [metrics, setMetrics] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (open) fetchAll();
  }, [open]);

  async function fetchAll() {
    setLoading(true);
    try {
      const [cfgR, statsR] = await Promise.all([
        fetch(`${API_URL}/api/collector/config`),
        fetch(`${API_URL}/api/collector/stats`),
      ]);
      const cfgData: CollectorConfig = await cfgR.json();
      const statsData: StoreStats = await statsR.json();
      setConfig(cfgData);
      setStats(statsData);
      setEnabled(cfgData.enabled);
      setInterval_(cfgData.interval_seconds);
      setMetrics({ ...cfgData.metrics });
    } catch {}
    setLoading(false);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await fetch(`${API_URL}/api/collector/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, interval_seconds: interval, metrics }),
      });
      await fetchAll();
    } catch {}
    setSaving(false);
  }

  async function handleCollectNow() {
    setCollecting(true);
    try {
      await fetch(`${API_URL}/api/collector/collect`, { method: "POST" });
      await fetchAll();
    } catch {}
    setCollecting(false);
  }

  function toggleMetric(key: string) {
    setMetrics(m => ({ ...m, [key]: !m[key] }));
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Collecteur de métriques"
        className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
      >
        <Activity size={14} />
      </button>

      {open && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setOpen(false)}>
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700">
              <div className="flex items-center gap-2">
                <Activity size={18} className="text-emerald-500" />
                <h3 className="font-semibold text-slate-800 dark:text-slate-100">Collecteur macOS (OTLP)</h3>
              </div>
              <button onClick={() => setOpen(false)} className="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400">
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              {loading ? (
                <div className="text-center py-8 text-slate-400">
                  <Loader2 size={20} className="animate-spin mx-auto mb-2" />
                </div>
              ) : (
                <>
                  {/* Store stats */}
                  {stats && (
                    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 px-4 py-3 text-xs space-y-1">
                      <div className="flex justify-between">
                        <span className="text-slate-500">Points stockés</span>
                        <span className="font-mono text-slate-700 dark:text-slate-300">{stats.total_points} / {stats.max_capacity}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500">Métriques actives</span>
                        <span className="font-mono text-slate-700 dark:text-slate-300">{stats.metrics.length}</span>
                      </div>
                      <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 mt-1">
                        <div className="bg-emerald-500 h-1.5 rounded-full transition-all" style={{ width: `${Math.min(100, (stats.total_points / stats.max_capacity) * 100)}%` }} />
                      </div>
                    </div>
                  )}

                  {/* Enable toggle */}
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">Collecte active</span>
                    <button
                      onClick={() => setEnabled(e => !e)}
                      className={`relative w-12 h-6 rounded-full transition-colors ${enabled ? "bg-emerald-500" : "bg-slate-300 dark:bg-slate-600"}`}
                    >
                      <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${enabled ? "translate-x-6" : ""}`} />
                    </button>
                  </div>

                  {/* Interval */}
                  <div>
                    <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                      Intervalle de collecte : {interval}s
                    </label>
                    <input
                      type="range" min={5} max={120} step={5}
                      value={interval}
                      onChange={e => setInterval_(Number(e.target.value))}
                      className="w-full"
                    />
                    <div className="flex justify-between text-xs text-slate-400">
                      <span>5s</span><span>30s</span><span>60s</span><span>120s</span>
                    </div>
                  </div>

                  {/* Metric toggles */}
                  <div>
                    <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">Métriques à collecter</label>
                    <div className="space-y-1.5">
                      {Object.entries(METRIC_LABELS).map(([key, label]) => (
                        <label key={key} className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={metrics[key] ?? true}
                            onChange={() => toggleMetric(key)}
                            className="w-4 h-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                          />
                          <span className="text-sm text-slate-700 dark:text-slate-200">{label}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Buttons */}
                  <div className="flex gap-2">
                    <button
                      onClick={handleCollectNow}
                      disabled={collecting}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition-all disabled:opacity-50"
                    >
                      {collecting
                        ? <><Loader2 size={14} className="animate-spin" /> Collecte...</>
                        : <><RefreshCw size={14} /> Collecter maintenant</>
                      }
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={saving}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-emerald-600 hover:bg-emerald-700 text-white transition-all disabled:opacity-50"
                    >
                      {saving
                        ? <><Loader2 size={14} className="animate-spin" /> ...</>
                        : <><Check size={14} /> Appliquer</>
                      }
                    </button>
                  </div>

                  <p className="text-xs text-slate-400 text-center">
                    Les métriques sont stockées en mémoire au format OpenTelemetry et requêtables via le chat (MCP).
                  </p>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
