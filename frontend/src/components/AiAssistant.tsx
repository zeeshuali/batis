import { useState, useRef, useEffect } from "react";
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const API_KEY = (import.meta.env.VITE_API_KEY as string) || "";

function apiHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

interface Source {
  content_type: string;
  content_id: string;
  similarity: number;
  snippet: string;
}

interface Message {
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
  loading?: boolean;
}

const SUGGESTED = [
  "Which routes have the worst delays this week?",
  "What is the on-time performance for route 1T?",
  "Are there any stops with consistently high delays?",
  "How does route 72 compare to route 72R?",
  "What routes serve the Fruitvale BART station area?",
];

export default function AiAssistant() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [ollamaReady, setOllamaReady] = useState<boolean | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    axios.get(`${API_BASE}/ai/status`)
      .then((r) => setOllamaReady(r.data.target_ready ?? false))
      .catch(() => setOllamaReady(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendQuestion(question: string) {
    if (!question.trim() || sending) return;
    setInput("");
    setSending(true);

    const userMsg: Message = { role: "user", text: question };
    const placeholder: Message = { role: "assistant", text: "", loading: true };
    setMessages((prev) => [...prev, userMsg, placeholder]);

    try {
      const { data } = await axios.post(`${API_BASE}/ai/ask`, { question }, { headers: apiHeaders() });
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: "assistant",
          text: data.answer ?? "No response received.",
          sources: data.sources ?? [],
        },
      ]);
    } catch (err: unknown) {
      const msg = axios.isAxiosError(err)
        ? (err.response?.data?.detail ?? err.message)
        : "Failed to reach the AI endpoint.";
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", text: `Error: ${msg}` },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="ai-assistant">
      {ollamaReady === false && (
        <div className="ai-status-banner">
          Local model offline. Run:{" "}
          <code>ollama serve &amp;&amp; ollama pull llama3.1:8b</code>
        </div>
      )}

      <div className="ai-messages">
        {messages.length === 0 && (
          <div className="ai-welcome">
            <p className="ai-welcome-title">AC Transit AI Assistant</p>
            <p className="ai-welcome-sub">
              Ask questions about routes, stops, delays, and service reliability.
            </p>
            <div className="ai-suggestions">
              {SUGGESTED.map((q) => (
                <button
                  key={q}
                  className="ai-suggestion-btn"
                  onClick={() => sendQuestion(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`ai-message ai-message--${msg.role}`}>
            <div className="ai-message-bubble">
              {msg.loading ? (
                <span className="ai-loading-dots">
                  <span />
                  <span />
                  <span />
                </span>
              ) : (
                msg.text
              )}
            </div>
            {msg.sources && msg.sources.length > 0 && (
              <details className="ai-sources">
                <summary>Sources ({msg.sources.length})</summary>
                {msg.sources.map((s, si) => (
                  <div key={si} className="ai-source-item">
                    <span className="ai-source-type">{s.content_type}</span>{" "}
                    <span className="ai-source-id">{s.content_id}</span>{" "}
                    <span className="ai-source-sim">
                      {(s.similarity * 100).toFixed(1)}%
                    </span>
                    <div className="ai-source-snippet">{s.snippet}</div>
                  </div>
                ))}
              </details>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        className="ai-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          sendQuestion(input);
        }}
      >
        <input
          className="ai-input"
          type="text"
          placeholder="Ask about AC Transit…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
        />
        <button className="ai-send-btn" type="submit" disabled={sending || !input.trim()}>
          {sending ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}
