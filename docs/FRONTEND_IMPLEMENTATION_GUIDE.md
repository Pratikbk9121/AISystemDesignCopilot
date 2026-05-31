# Frontend Implementation Guide
## AI System Design Copilot - Code Examples & Project Structure

---

## 📁 Recommended Project Structure

### React + TypeScript Example

```
frontend/
├── public/
│   └── index.html
├── src/
│   ├── api/
│   │   ├── client.ts              # API service layer
│   │   ├── types.ts               # TypeScript interfaces
│   │   └── endpoints.ts           # Endpoint constants
│   ├── components/
│   │   ├── Chat/
│   │   │   ├── ChatContainer.tsx
│   │   │   ├── MessageList.tsx
│   │   │   ├── MessageBubble.tsx
│   │   │   └── ChatInput.tsx
│   │   ├── Design/
│   │   │   ├── ArchitectureView.tsx
│   │   │   ├── ServiceCard.tsx
│   │   │   ├── DatabaseView.tsx
│   │   │   ├── TradeoffComparison.tsx
│   │   │   └── APIDesignList.tsx
│   │   ├── Evaluation/
│   │   │   ├── EvaluationPanel.tsx
│   │   │   ├── ConfidenceScore.tsx
│   │   │   └── SuggestionsCard.tsx
│   │   ├── Context/
│   │   │   ├── ContextForm.tsx
│   │   │   └── ContextChips.tsx
│   │   ├── Session/
│   │   │   ├── SessionManager.tsx
│   │   │   └── ConversationHistory.tsx
│   │   └── Common/
│   │       ├── Loading.tsx
│   │       ├── ErrorBoundary.tsx
│   │       ├── Toast.tsx
│   │       └── Button.tsx
│   ├── hooks/
│   │   ├── useSystemDesign.ts     # Main API hook
│   │   ├── useSession.ts          # Session management
│   │   └── useConversation.ts     # Conversation history
│   ├── store/
│   │   ├── designStore.ts         # State management
│   │   └── sessionStore.ts
│   ├── utils/
│   │   ├── validation.ts
│   │   ├── formatting.ts
│   │   └── storage.ts
│   ├── styles/
│   │   └── globals.css
│   ├── App.tsx
│   ├── main.tsx
│   └── vite-env.d.ts
├── package.json
├── tsconfig.json
├── vite.config.ts
└── README.md
```

---

## 🔧 Complete TypeScript Type Definitions

### `src/api/types.ts`

```typescript
// Request Types
export interface SystemDesignQuery {
  query: string;
  session_id?: string | null;
  include_evaluation?: boolean;
  context?: ContextParams | null;
}

export interface ContextParams {
  scale?: string;
  region?: string;
  budget?: 'low' | 'medium' | 'high';
  latency_requirement?: string;
  data_consistency?: 'strong' | 'eventual';
  availability_target?: string;
  team_size?: 'small' | 'medium' | 'large';
  timeline?: 'MVP' | '6 months' | 'production-ready';
  [key: string]: any;
}

// Response Types
export interface TradeOff {
  aspect: string;
  options: string[];
  recommendation: string;
  considerations: string[];
}

export interface SystemArchitecture {
  services: string[];
  database: string;
  scaling_strategy: string;
  tradeoffs: TradeOff[];
  key_components: Record<string, string>;
  data_flow: string | null;
  api_design: string[];
  non_functional_requirements: Record<string, string>;
}

export interface EvaluationResult {
  confidence_score: number;
  strengths: string[];
  weaknesses: string[];
  suggestions: string[];
  hallucination_check: boolean;
  completeness_score: number;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface ConfidenceMetrics {
  overall_confidence: number;
  confidence_level: 'HIGH' | 'MEDIUM' | 'LOW' | 'VERY_LOW';
  retrieval_confidence: number;
  coverage_confidence: number;
  num_docs_retrieved: number;
  avg_similarity_score: number;
  recommendation: string;
}

export interface SystemDesignResponse {
  query: string;
  session_id: string;
  architecture: SystemArchitecture;
  explanation: string;
  evaluation: EvaluationResult | null;
  token_usage: TokenUsage | null;
  retrieved_context: string[];
  confidence_metrics: ConfidenceMetrics | null;
  timestamp: string;
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  metadata: Record<string, any>;
}

export interface ConversationHistory {
  session_id: string;
  messages: ConversationMessage[];
  created_at: string;
  updated_at: string;
  metadata: Record<string, any>;
}

export interface HealthCheckResponse {
  status: string;
  service: string;
  version: string;
}

export interface ErrorResponse {
  detail: string;
  error?: string;
}

// ⚡ NEW: Streaming Event Types
export type StreamEventType =
  | 'metadata'
  | 'progress'
  | 'design_chunk'
  | 'design_complete'
  | 'evaluation'
  | 'done'
  | 'error';

export interface StreamEvent {
  type: StreamEventType;
  data: any;
}

export interface StreamMetadataEvent {
  session_id: string;
  query: string;
}

export interface StreamProgressEvent {
  step: string;
  message: string;
}

export interface StreamDesignChunkEvent {
  chunk: string;
}

export interface StreamDesignCompleteEvent {
  architecture: SystemArchitecture;
  explanation: string;
}
```

---

## 🌐 API Client Implementation

### `src/api/endpoints.ts`

```typescript
export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const API_VERSION = '/api/v1';

export const ENDPOINTS = {
  HEALTH: `${API_BASE_URL}${API_VERSION}/system-design/health`,
  QUERY: `${API_BASE_URL}${API_VERSION}/system-design/query`,
  QUERY_STREAM: `${API_BASE_URL}${API_VERSION}/system-design/query-stream`, // ⚡ NEW: Streaming endpoint
  CONVERSATION: (sessionId: string) =>
    `${API_BASE_URL}${API_VERSION}/system-design/conversation/${sessionId}`,
  ROOT: `${API_BASE_URL}/`,
} as const;
```

### `src/api/client.ts`

```typescript
import {
  SystemDesignQuery,
  SystemDesignResponse,
  ConversationHistory,
  HealthCheckResponse,
  ErrorResponse,
} from './types';
import { ENDPOINTS } from './endpoints';

class APIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public details?: any
  ) {
    super(message);
    this.name = 'APIError';
  }
}

export class SystemDesignAPI {
  private async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const errorData: ErrorResponse = await response.json().catch(() => ({
        detail: 'An unknown error occurred',
      }));
      throw new APIError(
        errorData.detail,
        response.status,
        errorData.error
      );
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  async healthCheck(): Promise<HealthCheckResponse> {
    const response = await fetch(ENDPOINTS.HEALTH);
    return this.handleResponse<HealthCheckResponse>(response);
  }

  async generateDesign(
    params: SystemDesignQuery
  ): Promise<SystemDesignResponse> {
    const response = await fetch(ENDPOINTS.QUERY, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(params),
    });

    return this.handleResponse<SystemDesignResponse>(response);
  }

  async getConversation(sessionId: string): Promise<ConversationHistory> {
    const response = await fetch(ENDPOINTS.CONVERSATION(sessionId));
    return this.handleResponse<ConversationHistory>(response);
  }

  async clearConversation(sessionId: string): Promise<void> {
    const response = await fetch(ENDPOINTS.CONVERSATION(sessionId), {
      method: 'DELETE',
    });
    return this.handleResponse<void>(response);
  }

  // ⚡ NEW: Streaming endpoint for faster perceived latency
  async *generateDesignStreaming(
    params: SystemDesignQuery
  ): AsyncGenerator<StreamEvent, void, unknown> {
    const response = await fetch(ENDPOINTS.QUERY_STREAM, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(params),
    });

    if (!response.ok) {
      const errorData: ErrorResponse = await response.json().catch(() => ({
        detail: 'Failed to start streaming',
      }));
      throw new APIError(errorData.detail, response.status, errorData.error);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event:')) {
            // Store event type
            const eventType = line.slice(6).trim() as StreamEventType;
            continue;
          }

          if (line.startsWith('data:')) {
            const dataStr = line.slice(5).trim();
            try {
              const data = JSON.parse(dataStr);
              const eventType = data.type || 'progress'; // Default to progress
              yield { type: eventType, data: data.data || data };
            } catch (e) {
              // Skip invalid JSON
              console.warn('Failed to parse SSE data:', dataStr);
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}

// Export singleton instance
export const api = new SystemDesignAPI();
```

---

## 🎣 React Hooks

### `src/hooks/useSystemDesign.ts`

```typescript
import { useState } from 'react';
import { api } from '../api/client';
import {
  SystemDesignQuery,
  SystemDesignResponse,
} from '../api/types';

export function useSystemDesign() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<SystemDesignResponse | null>(null);

  const generateDesign = async (params: SystemDesignQuery) => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await api.generateDesign(params);
      setResponse(result);
      return result;
    } catch (err: any) {
      const errorMessage = err.message || 'Failed to generate design';
      setError(errorMessage);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const reset = () => {
    setResponse(null);
    setError(null);
  };

  return {
    generateDesign,
    reset,
    isLoading,
    error,
    response,
  };
}
```

### `src/hooks/useSession.ts`

```typescript
import { useState, useEffect } from 'react';

const SESSION_KEY = 'ai-system-design-session-id';

export function useSession() {
  const [sessionId, setSessionId] = useState<string | null>(() => {
    return localStorage.getItem(SESSION_KEY);
  });

  useEffect(() => {
    if (sessionId) {
      localStorage.setItem(SESSION_KEY, sessionId);
    } else {
      localStorage.removeItem(SESSION_KEY);
    }
  }, [sessionId]);

  const startNewSession = () => {
    setSessionId(null);
  };

  const updateSession = (newSessionId: string) => {
    setSessionId(newSessionId);
  };

  return {
    sessionId,
    startNewSession,
    updateSession,
  };
}
```

### `src/hooks/useStreamingDesign.ts` ⚡ NEW

```typescript
import { useState, useCallback } from 'react';
import { api } from '../api/client';
import {
  SystemDesignQuery,
  SystemArchitecture,
  StreamEvent,
} from '../api/types';

export function useStreamingDesign() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [streamedContent, setStreamedContent] = useState<string>('');
  const [architecture, setArchitecture] = useState<SystemArchitecture | null>(null);
  const [progress, setProgress] = useState<string>('');

  const streamDesign = useCallback(async (params: SystemDesignQuery) => {
    setIsStreaming(true);
    setError(null);
    setStreamedContent('');
    setArchitecture(null);
    setProgress('Initializing...');

    try {
      for await (const event of api.generateDesignStreaming(params)) {
        switch (event.type) {
          case 'metadata':
            setSessionId(event.data.session_id);
            break;

          case 'progress':
            setProgress(event.data.message || event.data.step);
            break;

          case 'design_chunk':
            setStreamedContent(prev => prev + event.data.chunk);
            break;

          case 'design_complete':
            setArchitecture(event.data.architecture);
            setProgress('Complete!');
            break;

          case 'error':
            setError(event.data.message || 'An error occurred');
            break;

          case 'done':
            setProgress('');
            break;
        }
      }
    } catch (err: any) {
      const errorMessage = err.message || 'Failed to stream design';
      setError(errorMessage);
    } finally {
      setIsStreaming(false);
    }
  }, []);

  const reset = useCallback(() => {
    setStreamedContent('');
    setArchitecture(null);
    setError(null);
    setProgress('');
  }, []);

  return {
    streamDesign,
    reset,
    isStreaming,
    error,
    sessionId,
    streamedContent,
    architecture,
    progress,
  };
}
```

### `src/hooks/useConversation.ts`

```typescript
import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { ConversationHistory, ConversationMessage } from '../api/types';

export function useConversation(sessionId: string | null) {
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadConversation = async () => {
    if (!sessionId) {
      setMessages([]);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const history = await api.getConversation(sessionId);
      setMessages(history.messages);
    } catch (err: any) {
      if (err.statusCode === 404) {
        // Session not found, start fresh
        setMessages([]);
      } else {
        setError(err.message);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const addMessage = (message: ConversationMessage) => {
    setMessages(prev => [...prev, message]);
  };

  const clearMessages = async () => {
    if (sessionId) {
      await api.clearConversation(sessionId);
    }
    setMessages([]);
  };

  useEffect(() => {
    loadConversation();
  }, [sessionId]);

  return {
    messages,
    addMessage,
    clearMessages,
    isLoading,
    error,
    reload: loadConversation,
  };
}
```

---

## 🎨 Component Examples

### `src/components/Chat/ChatInput.tsx`

```typescript
import React, { useState } from 'react';
import { ContextParams } from '../../api/types';

interface ChatInputProps {
  onSubmit: (query: string, context?: ContextParams) => void;
  isLoading: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({ onSubmit, isLoading }) => {
  const [query, setQuery] = useState('');
  const [includeEvaluation, setIncludeEvaluation] = useState(false); // ⚡ CHANGED: Now disabled by default (faster!)
  const [showContext, setShowContext] = useState(false);
  const [context, setContext] = useState<ContextParams>({});

  const isValidQuery = query.length >= 10 && query.length <= 2000;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isValidQuery && !isLoading) {
      onSubmit(query, Object.keys(context).length > 0 ? context : undefined);
      setQuery('');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="chat-input">
      <div className="input-wrapper">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Describe your system design requirements (e.g., 'Design a URL shortener like bit.ly')..."
          rows={3}
          disabled={isLoading}
          className={query.length > 2000 ? 'error' : ''}
        />
        <div className="char-counter">
          {query.length} / 2000
          {query.length > 0 && query.length < 10 && (
            <span className="warning"> (minimum 10 characters)</span>
          )}
        </div>
      </div>

      <div className="options-row">
        <label>
          <input
            type="checkbox"
            checked={includeEvaluation}
            onChange={(e) => setIncludeEvaluation(e.target.checked)}
          />
          Include AI Evaluation <span className="badge-optional">+3-7s</span>
        </label>

        <button
          type="button"
          onClick={() => setShowContext(!showContext)}
          className="context-toggle"
        >
          {showContext ? 'Hide' : 'Add'} Context
        </button>
      </div>

      {showContext && (
        <div className="context-form">
          <input
            type="text"
            placeholder="Scale (e.g., 10M DAU)"
            value={context.scale || ''}
            onChange={(e) => setContext({ ...context, scale: e.target.value })}
          />
          <input
            type="text"
            placeholder="Region (e.g., Global)"
            value={context.region || ''}
            onChange={(e) => setContext({ ...context, region: e.target.value })}
          />
          <select
            value={context.budget || ''}
            onChange={(e) => setContext({ ...context, budget: e.target.value as any })}
          >
            <option value="">Select Budget</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>
      )}

      <button
        type="submit"
        disabled={!isValidQuery || isLoading}
        className="submit-btn"
      >
        {isLoading ? 'Generating...' : 'Generate Design'}
      </button>
    </form>
  );
};
```

### `src/components/Design/ArchitectureView.tsx`

```typescript
import React from 'react';
import { SystemArchitecture } from '../../api/types';
import { ServiceCard } from './ServiceCard';
import { TradeoffComparison } from './TradeoffComparison';

interface ArchitectureViewProps {
  architecture: SystemArchitecture;
}

export const ArchitectureView: React.FC<ArchitectureViewProps> = ({
  architecture,
}) => {
  return (
    <div className="architecture-view">
      {/* Services Section */}
      <section className="services-section">
        <h2>Services & Components</h2>
        <div className="services-grid">
          {architecture.services.map((service, index) => (
            <ServiceCard
              key={index}
              name={service}
              description={architecture.key_components[service]}
            />
          ))}
        </div>
      </section>

      {/* Database Section */}
      <section className="database-section">
        <h2>Database Architecture</h2>
        <div className="database-card">
          <p>{architecture.database}</p>
        </div>
      </section>

      {/* Scaling Strategy */}
      <section className="scaling-section">
        <h2>Scaling Strategy</h2>
        <div className="scaling-card">
          <p>{architecture.scaling_strategy}</p>
        </div>
      </section>

      {/* Trade-offs */}
      {architecture.tradeoffs.length > 0 && (
        <section className="tradeoffs-section">
          <h2>Architectural Trade-offs</h2>
          {architecture.tradeoffs.map((tradeoff, index) => (
            <TradeoffComparison key={index} tradeoff={tradeoff} />
          ))}
        </section>
      )}

      {/* Data Flow */}
      {architecture.data_flow && (
        <section className="dataflow-section">
          <h2>Data Flow</h2>
          <div className="dataflow-card">
            <p>{architecture.data_flow}</p>
          </div>
        </section>
      )}

      {/* API Design */}
      {architecture.api_design.length > 0 && (
        <section className="api-section">
          <h2>API Design</h2>
          <ul className="api-list">
            {architecture.api_design.map((endpoint, index) => (
              <li key={index}>
                <code>{endpoint}</code>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Non-Functional Requirements */}
      {Object.keys(architecture.non_functional_requirements).length > 0 && (
        <section className="nfr-section">
          <h2>Non-Functional Requirements</h2>
          <table className="nfr-table">
            <tbody>
              {Object.entries(architecture.non_functional_requirements).map(
                ([key, value]) => (
                  <tr key={key}>
                    <td className="nfr-key">{key}</td>
                    <td className="nfr-value">{value}</td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
};
```

### `src/components/Evaluation/EvaluationPanel.tsx`

```typescript
import React from 'react';
import { EvaluationResult, ConfidenceMetrics } from '../../api/types';
import { ConfidenceScore } from './ConfidenceScore';

interface EvaluationPanelProps {
  evaluation: EvaluationResult | null;
  confidenceMetrics: ConfidenceMetrics | null;
}

export const EvaluationPanel: React.FC<EvaluationPanelProps> = ({
  evaluation,
  confidenceMetrics,
}) => {
  if (!evaluation) {
    return null;
  }

  return (
    <div className="evaluation-panel">
      <h2>AI Evaluation</h2>

      {/* Confidence Scores */}
      <div className="scores-section">
        <ConfidenceScore
          label="Design Quality"
          score={evaluation.confidence_score}
        />
        <ConfidenceScore
          label="Completeness"
          score={evaluation.completeness_score}
        />
        {confidenceMetrics && (
          <div className="confidence-level">
            <span className={`badge ${confidenceMetrics.confidence_level.toLowerCase()}`}>
              {confidenceMetrics.confidence_level}
            </span>
          </div>
        )}
      </div>

      {/* Strengths */}
      {evaluation.strengths.length > 0 && (
        <div className="strengths-section">
          <h3>✅ Strengths</h3>
          <ul>
            {evaluation.strengths.map((strength, index) => (
              <li key={index} className="strength-item">
                {strength}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Weaknesses */}
      {evaluation.weaknesses.length > 0 && (
        <div className="weaknesses-section">
          <h3>⚠️ Potential Issues</h3>
          <ul>
            {evaluation.weaknesses.map((weakness, index) => (
              <li key={index} className="weakness-item">
                {weakness}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Suggestions */}
      {evaluation.suggestions.length > 0 && (
        <div className="suggestions-section">
          <h3>💡 Suggestions for Improvement</h3>
          <ul>
            {evaluation.suggestions.map((suggestion, index) => (
              <li key={index} className="suggestion-item">
                {suggestion}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Hallucination Check */}
      {!evaluation.hallucination_check && (
        <div className="warning-banner">
          ⚠️ This response may contain inaccurate information. Please verify.
        </div>
      )}
    </div>
  );
};
```

---

## 🔨 Utility Functions

### `src/utils/validation.ts`

```typescript
export const validateQuery = (query: string): {
  isValid: boolean;
  error?: string;
} => {
  if (query.length < 10) {
    return {
      isValid: false,
      error: 'Query must be at least 10 characters',
    };
  }

  if (query.length > 2000) {
    return {
      isValid: false,
      error: 'Query must not exceed 2000 characters',
    };
  }

  return { isValid: true };
};

export const getConfidenceColor = (score: number): string => {
  if (score >= 0.8) return 'green';
  if (score >= 0.6) return 'yellow';
  if (score >= 0.4) return 'orange';
  return 'red';
};

export const getConfidenceLevelClass = (
  level: 'HIGH' | 'MEDIUM' | 'LOW' | 'VERY_LOW'
): string => {
  return level.toLowerCase();
};
```

### `src/utils/formatting.ts`

```typescript
export const formatTimestamp = (timestamp: string): string => {
  const date = new Date(timestamp);
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
  }).format(date);
};

export const formatCost = (cost: number): string => {
  return `$${cost.toFixed(4)}`;
};

export const formatTokens = (tokens: number): string => {
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}k`;
  }
  return tokens.toString();
};

export const exportToJSON = (data: any, filename: string) => {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};
```

---

## 📦 Package.json Dependencies

```json
{
  "name": "ai-system-design-frontend",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx",
    "format": "prettier --write \"src/**/*.{ts,tsx,css}\""
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "zustand": "^4.4.0",
    "react-router-dom": "^6.20.0",
    "react-markdown": "^9.0.0",
    "react-syntax-highlighter": "^15.5.0",
    "clsx": "^2.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@typescript-eslint/eslint-plugin": "^6.0.0",
    "@typescript-eslint/parser": "^6.0.0",
    "@vitejs/plugin-react": "^4.2.0",
    "eslint": "^8.45.0",
    "eslint-plugin-react-hooks": "^4.6.0",
    "prettier": "^3.0.0",
    "typescript": "^5.0.0",
    "vite": "^5.0.0"
  }
}
```

---

## 🔐 Environment Variables

### `.env.example`

```bash
# API Configuration
VITE_API_URL=http://localhost:8000

# Feature Flags
VITE_ENABLE_EXPORT=true
VITE_ENABLE_HISTORY=true

# Debug
VITE_DEBUG=false
```

---

## 🚀 Quick Start Commands

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

---

## 🎯 Implementation Priorities

### Week 1: Core Features
1. ✅ Set up project structure
2. ✅ Implement API client
3. ✅ Create basic chat interface
4. ✅ Add query input with validation
5. ✅ Display architecture response

### Week 2: Enhanced UI
1. ✅ Add evaluation panel
2. ✅ Implement service cards
3. ✅ Create trade-off comparisons
4. ✅ Add loading states
5. ✅ Implement error handling

### Week 3: Session Management
1. ✅ Session persistence
2. ✅ Conversation history
3. ✅ Clear conversation
4. ✅ New conversation
5. ✅ Export functionality

### Week 4: Polish & Testing
1. ✅ Responsive design
2. ✅ Accessibility improvements
3. ✅ Performance optimization
4. ✅ Unit tests
5. ✅ E2E tests

---

## ⚡ NEW: Streaming Example Component

### `src/components/StreamingChat.tsx`

```typescript
import React, { useState } from 'react';
import { useStreamingDesign } from '../hooks/useStreamingDesign';
import { useSession } from '../hooks/useSession';
import { ChatInput } from './Chat/ChatInput';
import { ArchitectureView } from './Design/ArchitectureView';

export const StreamingChat: React.FC = () => {
  const { sessionId, updateSession } = useSession();
  const {
    streamDesign,
    isStreaming,
    error,
    streamedContent,
    architecture,
    progress,
    sessionId: newSessionId,
  } = useStreamingDesign();

  React.useEffect(() => {
    if (newSessionId) {
      updateSession(newSessionId);
    }
  }, [newSessionId, updateSession]);

  const handleSubmit = async (query: string, context?: any) => {
    await streamDesign({
      query,
      session_id: sessionId,
      include_evaluation: false, // Default to fast mode
      context,
    });
  };

  return (
    <div className="streaming-chat">
      <div className="chat-container">
        <ChatInput onSubmit={handleSubmit} isLoading={isStreaming} />

        {/* Progress Indicator */}
        {isStreaming && progress && (
          <div className="progress-bar">
            <div className="progress-message">{progress}</div>
            <div className="spinner" />
          </div>
        )}

        {/* Streaming Content (raw JSON as it arrives) */}
        {streamedContent && (
          <div className="streaming-content">
            <h3>⚡ Live Stream:</h3>
            <pre className="code-block">{streamedContent}</pre>
          </div>
        )}

        {/* Final Parsed Architecture */}
        {architecture && (
          <div className="architecture-result">
            <h2>✅ Complete Design</h2>
            <ArchitectureView architecture={architecture} />
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="error-message">
            <span className="error-icon">⚠️</span>
            {error}
          </div>
        )}
      </div>
    </div>
  );
};
```

### Usage Example

```typescript
// In your App.tsx or main component
import { StreamingChat } from './components/StreamingChat';

function App() {
  return (
    <div className="app">
      <header>
        <h1>AI System Design Copilot</h1>
        <span className="badge">⚡ Streaming Enabled</span>
      </header>

      <main>
        <StreamingChat />
      </main>
    </div>
  );
}
```

### Performance Comparison

```typescript
// Old approach (blocking):
const response = await api.generateDesign(params); // Wait 8-15s
console.log(response.architecture); // User waits...

// New approach (streaming): ⚡
for await (const event of api.generateDesignStreaming(params)) {
  if (event.type === 'design_chunk') {
    console.log('Chunk:', event.data.chunk); // User sees output in ~300ms!
  }
}
```

---

## 📝 Notes

- All timestamps are in ISO 8601 format
- Session IDs are UUIDs
- API automatically handles session creation
- Use sessionStorage for temporary sessions, localStorage for persistence
- Implement debouncing for better UX
- Consider using React Query for data fetching
- Add error boundaries for graceful error handling

### ⚡ Performance Optimizations (2026-05-01)

**Backend has been optimized for ultra-fast responses:**

1. **Streaming Endpoint** (`/query-stream`):
   - ✅ First response in ~300ms (vs 8-15s blocking)
   - ✅ Use `useStreamingDesign` hook for best UX
   - ✅ Server-Sent Events (SSE) protocol

2. **Evaluation Disabled by Default**:
   - ✅ Default: `include_evaluation: false` (fast mode)
   - ✅ Opt-in: Set to `true` if you need quality feedback
   - ✅ Saves 3-7 seconds when disabled
   - ⚠️ Update your UI to reflect this (checkbox should be unchecked by default)

3. **Multi-Query RAG**:
   - ✅ Now uses fast heuristic query expansion (no LLM call)
   - ✅ Parallel vector searches (4x faster)
   - ✅ Transparent to frontend

4. **Redis Caching** (if enabled on backend):
   - ✅ Repeat queries are instant (<100ms)
   - ✅ No frontend changes needed

**Recommended Frontend Approach:**
- 🚀 **Primary**: Use streaming endpoint for real-time feedback
- 💾 **Fallback**: Use regular endpoint for compatibility
- 🎯 **Toggle**: Let users choose between fast mode (no eval) and complete mode (with eval)

---

**Document Version**: 2.0.0
**Last Updated**: 2026-05-01
**Changes**: Added streaming support, updated evaluation defaults

