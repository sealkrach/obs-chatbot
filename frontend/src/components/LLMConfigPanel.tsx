import React, { useEffect, useState } from "react";
import { Settings, X, Check, Key, Globe, Cpu, Loader2, Zap, AlertCircle, CheckCircle2, RefreshCw } from "lucide-react";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8001";

interface LLMConfig {
  provider: string;
  openai_api_key_set: boolean;
  openai_api_key_preview: string;
  openai_model: string;
  openai_base_url: string;
  ollama_model: string;
}

interface TestResult {
  ok: boolean;
  error?: string;
  provider?: string;
  model?: string;
  model_available?: boolean;
  models_sample?: string[];
  models_available?: string[];
}

export default function LLMConfigPanel() {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState("");

  // Form state
  const [provider, setProvider] = useState("ollama");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o-mini");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [ollamaModel, setOllamaModel] = useState("llama3.1");

  useEffect(() => {
    if (open) { fetchConfig(); setTestResult(null); setAvailableModels([]); setModelsError(""); }
  }, [open]);

  async function fetchConfig() {
    setLoading(true);
    try {
      const r = await fetch(`${API_URL}/api/llm/config`);
      const data: LLMConfig = await r.json();
      setConfig(data);
      setProvider(data.provider);
      setModel(data.openai_model);
      setBaseUrl(data.openai_base_url);
      setOllamaModel(data.ollama_model);
      setApiKey("");
    } catch {}
    setLoading(false);
  }

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    setTestResult(null);
    try {
      await fetch(`${API_URL}/api/llm/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          openai_api_key: apiKey || "",
          openai_model: model,
          openai_base_url: baseUrl,
          ollama_model: ollamaModel,
        }),
      });
      setSaved(true);
      await fetchConfig();
      setTimeout(() => setSaved(false), 2000);
    } catch {}
    setSaving(false);
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    await handleSave();
    try {
      const r = await fetch(`${API_URL}/api/llm/test`, { method: "POST" });
      const data: TestResult = await r.json();
      setTestResult(data);
    } catch (e) {
      setTestResult({ ok: false, error: "Impossible de contacter le backend" });
    }
    setTesting(false);
  }

  async function handleFetchModels() {
    setFetchingModels(true);
    setModelsError("");
    setAvailableModels([]);
    // Save config first so backend uses current key/url
    await handleSave();
    try {
      const r = await fetch(`${API_URL}/api/llm/models`, { method: "POST" });
      const data = await r.json();
      if (data.ok) {
        setAvailableModels(data.models);
        if (data.models.length === 0) setModelsError("Aucun modèle trouvé");
      } else {
        setModelsError(data.error || "Erreur");
      }
    } catch {
      setModelsError("Impossible de contacter le backend");
    }
    setFetchingModels(false);
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Configuration LLM"
        className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
      >
        <Settings size={14} />
      </button>

      {open && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setOpen(false)}>
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700">
              <div className="flex items-center gap-2">
                <Cpu size={18} className="text-violet-500" />
                <h3 className="font-semibold text-slate-800 dark:text-slate-100">Configuration LLM</h3>
              </div>
              <button onClick={() => setOpen(false)} className="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400">
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              {loading ? (
                <div className="text-center py-8 text-slate-400">
                  <Loader2 size={20} className="animate-spin mx-auto mb-2" />
                  Chargement...
                </div>
              ) : (
                <>
                  {/* Provider toggle */}
                  <div>
                    <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">Provider</label>
                    <div className="flex gap-2">
                      {(["ollama", "openai"] as const).map(p => (
                        <button
                          key={p}
                          onClick={() => { setProvider(p); setTestResult(null); setAvailableModels([]); setModelsError(""); }}
                          className={`flex-1 px-3 py-2.5 rounded-xl text-sm font-medium transition-all border ${
                            provider === p
                              ? "bg-violet-50 dark:bg-violet-900/30 border-violet-300 dark:border-violet-700 text-violet-700 dark:text-violet-300"
                              : "bg-white dark:bg-slate-700 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:border-slate-300"
                          }`}
                        >
                          {p === "ollama" ? "🦙 Ollama (local)" : "🤖 OpenAI / Compatible"}
                        </button>
                      ))}
                    </div>
                  </div>

                  {provider === "openai" ? (
                    <>
                      {/* API Key */}
                      <div>
                        <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                          <Key size={12} className="inline mr-1" />
                          API Key
                        </label>
                        <input
                          type="password"
                          value={apiKey}
                          onChange={e => setApiKey(e.target.value)}
                          placeholder={config?.openai_api_key_set ? `Actuelle: ${config.openai_api_key_preview}` : "sk-..."}
                          className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                        />
                        {config?.openai_api_key_set && !apiKey && (
                          <p className="text-xs text-emerald-500 mt-1">✓ Clé API configurée</p>
                        )}
                      </div>

                      {/* Base URL */}
                      <div>
                        <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                          <Globe size={12} className="inline mr-1" />
                          Base URL
                        </label>
                        <input
                          value={baseUrl}
                          onChange={e => setBaseUrl(e.target.value)}
                          placeholder="https://api.openai.com/v1"
                          className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2 text-sm font-mono text-slate-800 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                        />
                        <p className="text-xs text-slate-400 mt-1">Compatible : OpenAI, Azure, Mistral, Groq, Together, etc.</p>
                      </div>

                      {/* Model — dynamic select + refresh */}
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-xs font-medium text-slate-500 dark:text-slate-400">Modèle</label>
                          <button
                            onClick={handleFetchModels}
                            disabled={fetchingModels}
                            className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:text-violet-700 disabled:text-slate-400"
                          >
                            <RefreshCw size={12} className={fetchingModels ? "animate-spin" : ""} />
                            {fetchingModels ? "Chargement…" : "Charger les modèles"}
                          </button>
                        </div>
                        {availableModels.length > 0 ? (
                          <select
                            value={model}
                            onChange={e => setModel(e.target.value)}
                            className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                          >
                            {availableModels.map(m => (
                              <option key={m} value={m}>{m}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            value={model}
                            onChange={e => setModel(e.target.value)}
                            placeholder="gpt-4o-mini"
                            className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                          />
                        )}
                        {modelsError && <p className="text-xs text-red-500 mt-1">{modelsError}</p>}
                        {availableModels.length > 0 && <p className="text-xs text-emerald-500 mt-1">{availableModels.length} modèles disponibles</p>}
                      </div>
                    </>
                  ) : (
                    /* Ollama — dynamic model select + refresh */
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-medium text-slate-500 dark:text-slate-400">Modèle Ollama</label>
                        <button
                          onClick={handleFetchModels}
                          disabled={fetchingModels}
                          className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:text-violet-700 disabled:text-slate-400"
                        >
                          <RefreshCw size={12} className={fetchingModels ? "animate-spin" : ""} />
                          {fetchingModels ? "Chargement…" : "Charger les modèles"}
                        </button>
                      </div>
                      {availableModels.length > 0 ? (
                        <select
                          value={ollamaModel}
                          onChange={e => setOllamaModel(e.target.value)}
                          className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                        >
                          {availableModels.map(m => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={ollamaModel}
                          onChange={e => setOllamaModel(e.target.value)}
                          placeholder="llama3.1"
                          className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                        />
                      )}
                      {modelsError && <p className="text-xs text-red-500 mt-1">{modelsError}</p>}
                      {availableModels.length > 0 && <p className="text-xs text-emerald-500 mt-1">{availableModels.length} modèles installés</p>}
                      <p className="text-xs text-slate-400 mt-1">Installer un modèle : <code className="bg-slate-100 dark:bg-slate-700 px-1 rounded">ollama pull mistral</code></p>
                    </div>
                  )}

                  {/* Test result */}
                  {testResult && (
                    <div className={`rounded-xl border px-4 py-3 text-sm ${
                      testResult.ok
                        ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300"
                        : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300"
                    }`}>
                      <div className="flex items-center gap-2 font-medium mb-1">
                        {testResult.ok
                          ? <><CheckCircle2 size={16} /> Connexion réussie</>
                          : <><AlertCircle size={16} /> Connexion échouée</>
                        }
                      </div>
                      {testResult.ok ? (
                        <div className="text-xs space-y-0.5">
                          <p>Provider : <span className="font-mono">{testResult.provider}</span></p>
                          <p>Modèle : <span className="font-mono">{testResult.model}</span> {testResult.model_available ? "✓" : "⚠ non trouvé"}</p>
                        </div>
                      ) : (
                        <p className="text-xs">{testResult.error}</p>
                      )}
                    </div>
                  )}

                  {/* Buttons */}
                  <div className="flex gap-2">
                    <button
                      onClick={handleTest}
                      disabled={testing || saving}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition-all disabled:opacity-50"
                    >
                      {testing ? (
                        <><Loader2 size={14} className="animate-spin" /> Test...</>
                      ) : (
                        <><Zap size={14} /> Tester</>
                      )}
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={saving}
                      className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
                        saved
                          ? "bg-emerald-500 text-white"
                          : "bg-violet-600 hover:bg-violet-700 text-white"
                      } disabled:opacity-50`}
                    >
                      {saving ? (
                        <><Loader2 size={14} className="animate-spin" /> ...</>
                      ) : saved ? (
                        <><Check size={14} /> OK !</>
                      ) : (
                        "Appliquer"
                      )}
                    </button>
                  </div>

                  <p className="text-xs text-slate-400 text-center">
                    Changer de provider réinitialise les sessions actives.
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
