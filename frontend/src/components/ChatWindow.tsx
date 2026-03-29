import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, CheckCircle, ChevronDown, ChevronRight,
         Loader2, RefreshCw, Send, Terminal, Trash2, Wifi, WifiOff } from "lucide-react";
import { useChat, type Message } from "../hooks/useChat";
import LLMConfigPanel from "./LLMConfigPanel";

// ── Utilitaire ────────────────────────────────────────────────────────

function cx(...classes: (string | false | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

// ── Composant : indicateur de connexion ──────────────────────────────

function ConnectionBadge({ state, onReconnect }: { state: string; onReconnect: () => void }) {
  const map: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
    connected:    { label: "Connecté",     color: "text-emerald-600 dark:text-emerald-400", icon: <Wifi size={13} /> },
    connecting:   { label: "Connexion…",   color: "text-amber-500",  icon: <Loader2 size={13} className="animate-spin" /> },
    disconnected: { label: "Déconnecté",   color: "text-slate-400",  icon: <WifiOff size={13} /> },
    error:        { label: "Erreur WS",    color: "text-red-500",    icon: <WifiOff size={13} /> },
  };
  const s = map[state] ?? map.disconnected;
  return (
    <div className={cx("flex items-center gap-1.5 text-xs font-medium", s.color)}>
      {s.icon}
      <span>{s.label}</span>
      {state !== "connected" && (
        <button onClick={onReconnect} className="ml-1 underline hover:no-underline text-xs">
          Reconnecter
        </button>
      )}
    </div>
  );
}

// ── Composant : tool_call collapsible ─────────────────────────────────

function ToolCallCard({ msg }: { msg: Message }) {
  const [open, setOpen] = useState(false);
  const tc = msg.toolCall!;
  return (
    <div className="flex justify-start mb-1">
      <div className="max-w-[80%] rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-xs font-mono overflow-hidden">
        <button
          onClick={() => setOpen(o => !o)}
          className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors"
        >
          <Terminal size={12} className="text-violet-500 shrink-0" />
          <span className="text-violet-600 dark:text-violet-400 font-semibold">{tc.tool}</span>
          <span className="text-slate-400 truncate flex-1">{tc.input}</span>
          {open
            ? <ChevronDown size={12} className="text-slate-400 shrink-0" />
            : <ChevronRight size={12} className="text-slate-400 shrink-0" />}
        </button>
        {open && (
          <div className="px-3 pb-3 pt-1 border-t border-slate-200 dark:border-slate-700">
            <p className="text-slate-500 dark:text-slate-400 mb-1">Résultat :</p>
            <p className="text-slate-700 dark:text-slate-300 whitespace-pre-wrap">{tc.output}</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Composant : bulle de message ──────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === "tool_call") return <ToolCallCard msg={msg} />;

  if (msg.role === "system") {
    return (
      <div className="flex justify-center my-1">
        <span className="text-xs text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 px-3 py-1 rounded-full">
          {msg.text}
        </span>
      </div>
    );
  }

  const isUser = msg.role === "user";
  return (
    <div className={cx("flex mb-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-violet-600 flex items-center justify-center text-white text-xs font-bold mr-2 mt-1 shrink-0">
          OB
        </div>
      )}
      <div
        className={cx(
          "max-w-[78%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-violet-600 text-white rounded-br-sm"
            : msg.error
              ? "bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-bl-sm"
              : "bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 rounded-bl-sm"
        )}
      >
        {isUser ? (
          <p>{msg.text}</p>
        ) : (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code: ({ children, className }) => {
                const isBlock = className?.startsWith("language-");
                return isBlock
                  ? <code className="block bg-slate-100 dark:bg-slate-700 rounded p-2 text-xs font-mono overflow-x-auto my-1">{children}</code>
                  : <code className="bg-slate-100 dark:bg-slate-700 rounded px-1 py-0.5 text-xs font-mono">{children}</code>;
              },
              strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
              ul: ({ children }) => <ul className="list-disc ml-4 space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal ml-4 space-y-0.5">{children}</ol>,
              h2: ({ children }) => <h2 className="font-semibold text-base mt-2 mb-1">{children}</h2>,
              h3: ({ children }) => <h3 className="font-semibold mt-1.5 mb-0.5">{children}</h3>,
            }}
          >
            {msg.text}
          </ReactMarkdown>
        )}
        {msg.error && (
          <div className="flex items-center gap-1 mt-1 text-xs text-red-500">
            <AlertTriangle size={12} /> Vérifiez qu'Ollama est démarré
          </div>
        )}
      </div>
    </div>
  );
}

// ── Composant : suggestions rapides ───────────────────────────────────

const SUGGESTIONS = [
  "Alertes critiques actives ?",
  "CPU et mémoire actuels",
  "Forecast disque 30 jours",
  "Rapport du jour",
];

function Suggestions({ onSelect }: { onSelect: (s: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2 px-4 pb-3">
      {SUGGESTIONS.map(s => (
        <button
          key={s}
          onClick={() => onSelect(s)}
          className="text-xs px-3 py-1.5 rounded-full border border-violet-200 dark:border-violet-800 text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/30 transition-colors"
        >
          {s}
        </button>
      ))}
    </div>
  );
}

// ── Composant principal : ChatWindow ──────────────────────────────────

export default function ChatWindow() {
  const sessionId = useRef(Math.random().toString(36).slice(2, 10)).current;
  const { messages, connState, isThinking, sendMessage, clearHistory, reconnect } = useChat(sessionId);
  const [input, setInput]         = useState("");
  const [showTools, setShowTools] = useState(true);
  const bottomRef                 = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  const handleSend = () => {
    if (!input.trim() || connState !== "connected") return;
    sendMessage(input.trim());
    setInput("");
  };

  const visibleMessages = showTools
    ? messages
    : messages.filter(m => m.role !== "tool_call");

  return (
    <div className="flex flex-col h-screen bg-slate-50 dark:bg-slate-900 font-sans">

      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-violet-600 flex items-center justify-center text-white text-sm font-bold">
            OB
          </div>
          <div>
            <p className="font-semibold text-sm text-slate-800 dark:text-slate-100">Assistant Observabilité</p>
            <p className="text-xs text-slate-400">Ollama · llama3.1</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <ConnectionBadge state={connState} onReconnect={reconnect} />
          <LLMConfigPanel />
          <button
            onClick={() => setShowTools(t => !t)}
            title={showTools ? "Masquer les appels outils" : "Afficher les appels outils"}
            className={cx(
              "p-1.5 rounded-lg transition-colors text-xs",
              showTools
                ? "bg-violet-100 dark:bg-violet-900/40 text-violet-600"
                : "text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700"
            )}
          >
            <Terminal size={14} />
          </button>
          <button
            onClick={clearHistory}
            title="Effacer la conversation"
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 pt-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center pb-10">
            <div className="w-14 h-14 rounded-2xl bg-violet-100 dark:bg-violet-900/40 flex items-center justify-center mb-4">
              <CheckCircle size={28} className="text-violet-500" />
            </div>
            <p className="font-semibold text-slate-700 dark:text-slate-200 mb-1">Prêt à analyser ton infra</p>
            <p className="text-sm text-slate-400 max-w-xs">
              Pose une question sur les alertes, métriques, capacité ou demande un rapport.
            </p>
          </div>
        )}

        {visibleMessages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {isThinking && (
          <div className="flex justify-start mb-3">
            <div className="w-7 h-7 rounded-full bg-violet-600 flex items-center justify-center text-white text-xs font-bold mr-2 mt-1 shrink-0">OB</div>
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1 items-center">
                <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions (only when empty) */}
      {messages.length === 0 && (
        <Suggestions onSelect={s => { sendMessage(s); }} />
      )}

      {/* Input */}
      <div className="px-4 pb-4 pt-2 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
            }}
            placeholder="Ex: Quelles alertes critiques ? · CPU api-gateway · Rapport du jour…"
            rows={1}
            disabled={connState !== "connected" || isThinking}
            className={cx(
              "flex-1 resize-none rounded-xl border px-3.5 py-2.5 text-sm",
              "bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-100",
              "border-slate-200 dark:border-slate-600",
              "focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "placeholder:text-slate-400"
            )}
            style={{ maxHeight: "120px" }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || connState !== "connected" || isThinking}
            className={cx(
              "p-2.5 rounded-xl transition-all shrink-0",
              input.trim() && connState === "connected" && !isThinking
                ? "bg-violet-600 hover:bg-violet-700 text-white"
                : "bg-slate-100 dark:bg-slate-700 text-slate-400 cursor-not-allowed"
            )}
          >
            {isThinking
              ? <Loader2 size={18} className="animate-spin" />
              : <Send size={18} />}
          </button>
        </div>
        <p className="text-xs text-slate-400 mt-1.5 text-center">
          Entrée pour envoyer · Shift+Entrée pour nouvelle ligne · /reset pour effacer
        </p>
      </div>
    </div>
  );
}
