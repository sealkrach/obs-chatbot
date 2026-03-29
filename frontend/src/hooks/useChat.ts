import { useCallback, useEffect, useRef, useState } from "react";

export type MessageRole = "user" | "assistant" | "system" | "tool_call";

export interface ToolCall {
  tool:   string;
  input:  string;
  output: string;
}

export interface Message {
  id:        string;
  role:      MessageRole;
  text:      string;
  toolCall?: ToolCall;
  ts:        number;
  error?:    boolean;
}

export type ConnectionState = "connecting" | "connected" | "disconnected" | "error";

const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8001/ws/chat";

function genId() {
  return Math.random().toString(36).slice(2, 10);
}

export function useChat(sessionId: string) {
  const [messages,    setMessages]    = useState<Message[]>([]);
  const [connState,   setConnState]   = useState<ConnectionState>("disconnected");
  const [isThinking,  setIsThinking]  = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const addMessage = useCallback((msg: Omit<Message, "id" | "ts">) => {
    setMessages(prev => [...prev, { ...msg, id: genId(), ts: Date.now() }]);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setConnState("connecting");
    const ws = new WebSocket(`${WS_URL}/${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnState("connected");
    };

    ws.onclose = () => {
      setConnState("disconnected");
      setIsThinking(false);
    };

    ws.onerror = () => {
      setConnState("error");
      setIsThinking(false);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case "thinking":
            setIsThinking(true);
            break;

          case "tool_call":
            addMessage({
              role: "tool_call",
              text: `**${data.tool}**`,
              toolCall: { tool: data.tool, input: data.input, output: data.output },
            });
            break;

          case "answer":
            setIsThinking(false);
            addMessage({ role: "assistant", text: data.text });
            break;

          case "error":
            setIsThinking(false);
            addMessage({ role: "assistant", text: data.text, error: true });
            break;

          case "system":
            addMessage({ role: "system", text: data.text });
            break;
        }
      } catch {
        // ignore malformed messages
      }
    };
  }, [sessionId, addMessage]);

  // Auto-connect
  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback((text: string) => {
    if (!text.trim()) return;
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      connect();
      return;
    }
    addMessage({ role: "user", text });
    wsRef.current.send(JSON.stringify({ message: text }));
    setIsThinking(true);
  }, [connect, addMessage]);

  const clearHistory = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ message: "/reset" }));
    }
    setMessages([]);
  }, []);

  const reconnect = useCallback(() => {
    wsRef.current?.close();
    setTimeout(connect, 200);
  }, [connect]);

  return { messages, connState, isThinking, sendMessage, clearHistory, reconnect };
}
