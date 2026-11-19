import { useState, useRef, useCallback, useEffect } from 'react';
import { Send, Square, Paperclip, Search, X } from 'lucide-react';
import { toast } from 'sonner';
import { useAppStore, generateId } from '../../lib/store';
import { useTtsStore } from '../../lib/tts';
import { cancelChat, streamChat, streamResearch } from '../../lib/sse';
import { fetchSavings, getBase } from '../../lib/api';
import {
  CHAT_FILE_ACCEPT,
  CHAT_MAX_BYTES_PER_FILE,
  CHAT_MAX_FILES,
  composeChatContent,
  uploadChatAttachments,
} from '../../lib/chat-attachments';
import { listConnectors, getSyncStatus } from '../../lib/connectors-api';
import { serializeToolCallArguments } from '../../lib/tool-call';
import { shouldUseIndexedResearch, shouldUseLiveWebTools } from '../../lib/connected-source-routing';
import {
  engineFromCompletionChunk,
  resolveChatEngine,
} from '../../lib/chat-telemetry';
import { MicButton } from './MicButton';
import { useSpeech } from '../../hooks/useSpeech';
import type {
  ChatAttachment,
  ChatMessage,
  MessageTelemetry,
  ResearchSearchTrace,
  ResearchSource,
  TokenUsage,
  ToolCallInfo,
} from '../../types';

// While Deep Research is toggled on, poll connected sources for sync
// progress so we can surface "Searching over N items — sync in progress"
// next to the toggle. Polling is gated on `enabled` so toggling DR off
// stops the network chatter immediately.
function useResearchCorpusSync(enabled: boolean): {
  syncing: boolean;
  itemsSynced: number;
} {
  const [state, setState] = useState({ syncing: false, itemsSynced: 0 });

  useEffect(() => {
    if (!enabled) {
      setState({ syncing: false, itemsSynced: 0 });
      return;
    }
    let cancelled = false;

    const poll = async () => {
      try {
        const list = await listConnectors();
        const connected = list.filter((c) => c.connected);
        if (connected.length === 0) {
          if (!cancelled) setState({ syncing: false, itemsSynced: 0 });
          return;
        }
        const results = await Promise.all(
          connected.map(async (c) => {
            try {
              return await getSyncStatus(c.connector_id);
            } catch {
              return null;
            }
          }),
        );
        let syncing = false;
        let itemsSynced = 0;
        for (const r of results) {
          if (!r) continue;
          if (r.state === 'syncing') syncing = true;
          itemsSynced += r.items_synced ?? 0;
        }
        if (!cancelled) setState({ syncing, itemsSynced });
      } catch {
        // Network blip — leave previous state intact.
      }
    };

    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [enabled]);

  return state;
}

export function InputArea() {
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadBusyRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const chatRequestIdRef = useRef<string | null>(null);
  const cancellationReasons = useRef(new WeakMap<AbortController, string>());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const modelSelectionEpoch = useAppStore((s) => s.modelSelectionEpoch);
  const streamState = useAppStore((s) => s.streamState);
  const messages = useAppStore((s) => s.messages);
  const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
  const maxTokens = useAppStore((s) => s.settings.maxTokens);
  const temperature = useAppStore((s) => s.settings.temperature);
  const createConversation = useAppStore((s) => s.createConversation);
  const addMessage = useAppStore((s) => s.addMessage);
  const updateLastAssistant = useAppStore((s) => s.updateLastAssistant);
  const setStreamState = useAppStore((s) => s.setStreamState);
  const resetStream = useAppStore((s) => s.resetStream);
  const modelLoading = useAppStore((s) => s.modelLoading);
  const deepResearch = useAppStore((s) => s.deepResearch);
  const setDeepResearch = useAppStore((s) => s.setDeepResearch);
  const corpusSync = useResearchCorpusSync(deepResearch);
  const isCurrentChatStreaming = streamState.isStreaming && streamState.conversationId === activeId;

  const {
    state: speechState,
    error: speechError,
    available: speechAvailable,
    startRecording,
    stopRecording,
  } = useSpeech();

  // Signal cancellation to the backend before disconnecting the SSE reader.
  const cancelActiveChat = useCallback((reason: 'stop-button' | 'model-picker') => {
    const controller = abortRef.current;
    const requestId = chatRequestIdRef.current;
    chatRequestIdRef.current = null;
    if (controller) {
      cancellationReasons.current.set(controller, reason);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Chat cancellation requested: ${reason}; requestId=${requestId ?? 'none'}`,
      });
    }
    if (!requestId) {
      controller?.abort();
      return;
    }
    void cancelChat(requestId)
      .then((acknowledged) => {
        if (!acknowledged) {
          toast.warning('Stop was not acknowledged by OpenJarvis; Colibri may still be running.');
        }
      })
      .finally(() => controller?.abort());
  }, []);

  // Auto-discovery can replace a temporarily missing model in the selector.
  // That is NOT permission to cancel the in-flight request: sendMessage has
  // already captured its original model and conversation. Only an explicit
  // choice in the model picker increments modelSelectionEpoch.
  const prevSelectionRef = useRef({ model: selectedModel, epoch: modelSelectionEpoch });
  useEffect(() => {
    const prev = prevSelectionRef.current;
    const changed = prev.model !== selectedModel;
    const explicitlyChanged = changed && prev.epoch !== modelSelectionEpoch;
    if (explicitlyChanged) {
      if (streamState.isStreaming) {
        cancelActiveChat('model-picker');
        const allMessages = useAppStore.getState().messages;
        const current = allMessages[allMessages.length - 1];
        if (current?.role === 'assistant') useTtsStore.getState().markAutoSpoken(current.id);
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
        resetStream();
        abortRef.current = null;
      }
      useTtsStore.getState().stop();
    } else if (changed && streamState.isStreaming) {
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'warn', category: 'chat',
        message: `Automatic model catalog refresh: ${prev.model} → ${selectedModel}; active chat kept running`,
      });
    }
    prevSelectionRef.current = { model: selectedModel, epoch: modelSelectionEpoch };
  }, [selectedModel, modelSelectionEpoch, streamState.isStreaming, resetStream, cancelActiveChat]);

  const micDisabled = !speechEnabled || !speechAvailable || streamState.isStreaming;
  const micReason: 'not-enabled' | 'no-backend' | 'streaming' | undefined =
    !speechEnabled ? 'not-enabled'
    : !speechAvailable ? 'no-backend'
    : streamState.isStreaming ? 'streaming'
    : undefined;

  useEffect(() => {
    if (speechError) {
      toast.error(speechError, { duration: 8000 });
    }
  }, [speechError]);

  const handleMicClick = useCallback(async () => {
    if (speechState === 'recording') {
      try {
        const text = await stopRecording();
        if (text) {
          setInput((prev) => (prev ? prev + ' ' + text : text));
        }
      } catch {
        // Error is captured in useSpeech
      }
    } else {
      await startRecording();
    }
  }, [speechState, startRecording, stopRecording]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [input]);

  const stopStreaming = useCallback(() => {
    const allMessages = useAppStore.getState().messages;
    const last = allMessages[allMessages.length - 1];
    if (last?.role === 'assistant') useTtsStore.getState().markAutoSpoken(last.id);
    useTtsStore.getState().stop();
    cancelActiveChat('stop-button');
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    resetStream();
  }, [resetStream, cancelActiveChat]);

  const attachFiles = useCallback((files: File[]) => {
    const candidates = files.filter((file) => {
      if (file.size > CHAT_MAX_BYTES_PER_FILE) {
        toast.error(`${file.name} is too large (5 MB maximum).`);
        return false;
      }
      const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
      if (!CHAT_FILE_ACCEPT.split(',').includes(ext)) {
        toast.error(`${file.name}: unsupported file type.`);
        return false;
      }
      return true;
    });
    setPendingFiles((current) => {
      const added = [...current];
      for (const file of candidates) {
        if (added.some((item) =>
          item.name === file.name &&
          item.size === file.size &&
          item.lastModified === file.lastModified
        )) continue;
        if (added.length >= CHAT_MAX_FILES) {
          toast.error(`You can attach up to ${CHAT_MAX_FILES} files.`);
          break;
        }
        added.push(file);
      }
      return added;
    });
  }, []);

  const sendMessage = useCallback(async () => {
    const content = input.trim();
    if ((!content && pendingFiles.length === 0) || streamState.isStreaming || uploadBusyRef.current) return;
    // Deep Research is a separate indexed-source API; files go to Chat.
    const useResearch = pendingFiles.length === 0 && shouldUseIndexedResearch(content, deepResearch);
    if (deepResearch && shouldUseLiveWebTools(content)) {
      toast.info('Using Browser tools for this external link. Deep Research searches indexed personal data only.');
    }
    if (!selectedModel) {
      toast.error('Pick a model first (⌘K)');
      return;
    }

    let attached: ChatAttachment[] = [];
    if (pendingFiles.length > 0) {
      uploadBusyRef.current = true;
      setUploadingFiles(true);
      try {
        attached = await uploadChatAttachments(pendingFiles);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'File attachment failed.');
        return; // Keep the draft and files for retry.
      } finally {
        uploadBusyRef.current = false;
        setUploadingFiles(false);
      }
    }

    // A new user request always interrupts any remaining assistant audio.
    useTtsStore.getState().stop();
    setInput('');
    setPendingFiles([]);

    let convId = activeId;
    if (!convId) {
      convId = createConversation(selectedModel);
    }

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: content || 'Analyze the attached files.',
      attachments: attached.length ? attached : undefined,
      timestamp: Date.now(),
    };
    addMessage(convId, userMsg);

    // Build API messages before adding assistant placeholder
    const currentMessages = useAppStore.getState().messages;
    const apiMessages = currentMessages.map((m) => ({
      role: m.role,
      content: composeChatContent(m),
    }));

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isResearch: useResearch || undefined,
    };
    addMessage(convId, assistantMsg);

    // Start streaming
    const startTime = Date.now();
    const timer = setInterval(() => {
      setStreamState({ elapsedMs: Date.now() - startTime });
    }, 100);
    timerRef.current = timer;

    const controller = new AbortController();
    abortRef.current = controller;
    const chatRequestId = useResearch ? null : crypto.randomUUID();
    chatRequestIdRef.current = chatRequestId;

    let accumulatedContent = '';
    let usage: TokenUsage | undefined;
    let complexity: { score: number; tier: string; suggested_max_tokens: number } | undefined;
    let routedEngine: string | undefined;
    let serverPerformance: Record<string, unknown> | undefined;
    const toolCalls: ToolCallInfo[] = [];
    const researchTraces: ResearchSearchTrace[] = [];
    const researchSourcesByRef = new Map<number, ResearchSource>();
    const flushSources = () =>
      Array.from(researchSourcesByRef.values()).sort((a, b) => a.ref - b.ref);
    let lastFlush = 0;
    let ttftMs: number | undefined;

    setStreamState({
      conversationId: convId,
      isStreaming: true,
      phase: useResearch ? 'Searching connected sources...' : 'Generating...',
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    });
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: useResearch
        ? `Research: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}"`
        : `Request: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${selectedModel}`,
    });

    try {
      if (useResearch) {
        for await (const ev of streamResearch(
          content,
          selectedModel,
          controller.signal,
        )) {
          if (ev.type === 'search_call') {
            const trace: ResearchSearchTrace = {
              id: generateId(),
              query: ev.arguments?.query ?? '',
              person: ev.arguments?.person,
              timeRange: ev.arguments?.time_range,
              status: 'pending',
            };
            researchTraces.push(trace);
            setStreamState({ phase: `Searching: ${trace.query}` });
            updateLastAssistant(
              convId,
              accumulatedContent,
              undefined,
              undefined,
              undefined,
              undefined,
              [...researchTraces],
              flushSources(),
            );
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(),
              level: 'info',
              category: 'tool',
              message: `Search: "${trace.query}"${trace.person ? ` (person: ${trace.person})` : ''}`,
            });
          } else if (ev.type === 'search_result') {
            const pending = [...researchTraces].reverse().find((t) => t.status === 'pending');
            if (pending) {
              pending.status = 'complete';
              pending.numHits = ev.num_hits;
              pending.topTitles = ev.top_titles;
            }
            if (ev.sources) {
              for (const src of ev.sources) {
                if (src && typeof src.ref === 'number' && !researchSourcesByRef.has(src.ref)) {
                  researchSourcesByRef.set(src.ref, src);
                }
              }
            }
            updateLastAssistant(
              convId,
              accumulatedContent,
              undefined,
              undefined,
              undefined,
              undefined,
              [...researchTraces],
              flushSources(),
            );
          } else if (ev.type === 'synthesis') {
            if (!ttftMs) ttftMs = Date.now() - startTime;
            accumulatedContent += ev.text;
            setStreamState({ content: accumulatedContent, phase: '' });
            const now = Date.now();
            if (now - lastFlush >= 80) {
              updateLastAssistant(
                convId,
                accumulatedContent,
                undefined,
                undefined,
                undefined,
                undefined,
                [...researchTraces],
                flushSources(),
              );
              lastFlush = now;
            }
          } else if (ev.type === 'system_metrics') {
            // Live GPU sample — feed straight to the System panel so Power
            // (W) and Energy (kJ) tick up in real time as the agent runs.
            useAppStore.getState().setLiveEnergy({
              power_w: ev.power_w,
              energy_j: ev.energy_j,
              duration_s: ev.duration_s,
            });
          } else if (ev.type === 'error') {
            // Backend setup/worker failure (Ollama down, planner model
            // missing, KnowledgeStore locked, etc.). Without surfacing the
            // message, the user sees only the generic "No response was
            // generated" fallback and has no way to self-diagnose.
            const msg = ev.message || 'Research failed (no detail provided)';
            accumulatedContent = accumulatedContent
              ? `${accumulatedContent}\n\n**Research stopped:** ${msg}`
              : `**Research failed:** ${msg}`;
            setStreamState({ content: accumulatedContent, phase: '' });
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(),
              level: 'error',
              category: 'chat',
              message: `Deep Research error: ${msg}`,
            });
            toast.error(msg, { duration: 8000 });
          } else if (ev.type === 'done') {
            if (ev.usage) {
              usage = {
                prompt_tokens: ev.usage.prompt_tokens ?? 0,
                completion_tokens: ev.usage.completion_tokens ?? 0,
                total_tokens:
                  ev.usage.total_tokens ??
                  (ev.usage.prompt_tokens ?? 0) +
                    (ev.usage.completion_tokens ?? 0),
              };
              // Optimistically roll this research turn into the session
              // counters so the Session panel updates the moment the
              // stream finishes, regardless of how /v1/savings aggregates
              // research telemetry server-side.
              useAppStore.getState().incrementSavings(usage);
            }
            // Hold the final live numbers visible for a beat so the panel
            // doesn't flash to 0 between the SSE close and the next
            // /v1/telemetry/energy poll picking up the persisted record.
            window.setTimeout(() => {
              useAppStore.getState().setLiveEnergy(null);
            }, 1500);
            break;
          }
        }
      } else {
      for await (const sseEvent of streamChat(
        { model: selectedModel, messages: apiMessages, stream: true, temperature, max_tokens: maxTokens },
        controller.signal,
        chatRequestId ?? undefined,
      )) {
        const eventName = sseEvent.event;

        if (eventName === 'agent_turn_start') {
          setStreamState({ phase: 'Agent thinking...' });
        } else if (eventName === 'inference_start') {
          setStreamState({ phase: 'Generating...' });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'info', category: 'chat',
            message: `Generating with ${selectedModel}...`,
          });
        } else if (eventName === 'tool_call_start') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc: ToolCallInfo = {
              id: generateId(),
              tool: data.tool,
              arguments: serializeToolCallArguments(data.arguments),
              status: 'running',
            };
            toolCalls.push(tc);
            setStreamState({
              phase: `Calling ${data.tool}...`,
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(), level: 'info', category: 'tool',
              message: `Calling ${data.tool}(${serializeToolCallArguments(data.arguments)})`,
            });
          } catch {}
        } else if (eventName === 'tool_call_end') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc = toolCalls.find(
              (t) => t.tool === data.tool && t.status === 'running',
            );
            if (tc) {
              tc.status = data.success ? 'success' : 'error';
              tc.latency = data.latency;
              tc.result = data.result;
            }
            setStreamState({
              phase: 'Generating...',
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
          } catch {}
        } else {
          try {
            const data = JSON.parse(sseEvent.data);
            const delta = data.choices?.[0]?.delta;
            if (data.usage) usage = data.usage;
            if (data.complexity) complexity = data.complexity;
            if (data.performance && typeof data.performance === 'object') {
              serverPerformance = data.performance;
            }
            routedEngine = engineFromCompletionChunk(data) ?? routedEngine;
            if (delta?.content) {
              if (!ttftMs) ttftMs = Date.now() - startTime;
              accumulatedContent += delta.content;
              setStreamState({ content: accumulatedContent, phase: '' });

              const now = Date.now();
              if (now - lastFlush >= 80) {
                updateLastAssistant(
                  convId,
                  accumulatedContent,
                  toolCalls.length > 0 ? [...toolCalls] : undefined,
                );
                lastFlush = now;
              }
            }
// Do not stop reading at finish_reason: the backend sends [DONE]
            // only after completing agent finalization and cleanup. The SSE
            // reader validates that marker, so a dropped connection is an
            // explicit error instead of an apparently successful reply.
          } catch {}
        }
      }
      }
    } catch (err: any) {
      if (err?.name === 'AbortError' && cancellationReasons.current.has(controller)) {
        // Show "Generation stopped" only for a deliberate Stop or model pick.
        if (!accumulatedContent) accumulatedContent = '(Generation stopped)';
      } else {
        const errMsg = err?.message || String(err);
        const unexpectedAbort = err?.name === 'AbortError';
        accumulatedContent = accumulatedContent || (unexpectedAbort
          ? 'Error: Chat connection was interrupted unexpectedly. Check Logs for details.'
          : `Error: ${errMsg}`);
        useAppStore.getState().addLogEntry({
          timestamp: Date.now(), level: 'error', category: 'chat',
          message: unexpectedAbort
            ? `Unexpected AbortError without Stop: model=${selectedModel}, aborted=${controller.signal.aborted}, requestId=${chatRequestId ?? 'none'}`
            : `Stream error: ${errMsg}`,
        });
      }
      // If we tore out mid-research, make sure the live System panel
      // numbers don't get stuck on the last sample.
      useAppStore.getState().setLiveEnergy(null);
    } finally {
      if (!accumulatedContent) {
        accumulatedContent = 'No response was generated. Please try again.';
      }
      const totalMs = Date.now() - startTime;
      const appState = useAppStore.getState();
      const selectedOwner = appState.models.find((m) => m.id === selectedModel)?.owned_by;
      const engineLabel = resolveChatEngine({
        routedEngine,
        serverEngine: appState.serverInfo?.engine,
        selectedModel,
        selectedOwner,
      });
      const perfNumber = (key: string): number | undefined => {
        const value = serverPerformance?.[key];
        return typeof value === 'number' ? value : undefined;
      };
      const perfMs = (key: string): number | undefined => {
        const value = perfNumber(key);
        return value == null ? undefined : value * 1000;
      };
      const generationMs = ttftMs == null ? totalMs : Math.max(1, totalMs - ttftMs);
      const telemetry: MessageTelemetry = {
        engine: engineLabel,
        model_id: selectedModel,
        total_ms: totalMs,
        ttft_ms: ttftMs,
        agent_first_content_ms: perfMs('first_content_seconds'),
        model_first_content_ms: perfMs('model_first_content_seconds'),
        agent_total_ms: perfMs('agent_wall_seconds'),
        inference_total_ms: perfMs('inference_wall_seconds'),
        prompt_chars: perfNumber('prompt_chars'),
        advertised_tool_count: perfNumber('advertised_tool_count'),
        registered_tool_count: perfNumber('registered_tool_count'),
        prompt_tokens_estimated: serverPerformance?.prompt_tokens_estimated === true,
        tokens_per_sec: usage?.completion_tokens
          ? usage.completion_tokens / (generationMs / 1000)
          : undefined,
        complexity_score: complexity?.score,
        complexity_tier: complexity?.tier,
        suggested_max_tokens: complexity?.suggested_max_tokens,
      };
      // Check if the response has digest audio available
      let audioMeta: { url: string } | undefined;
      try {
        const digestRes = await fetch(`${getBase()}/api/digest`);
        if (digestRes.ok) {
          const digest = await digestRes.json();
          if (digest.audio_available) {
            audioMeta = { url: `${getBase()}/api/digest/audio` };
          }
        }
      } catch {
        // Not a digest response or server unavailable — skip
      }

      updateLastAssistant(
        convId,
        accumulatedContent,
        toolCalls.length > 0 ? toolCalls : undefined,
        usage,
        telemetry,
        audioMeta,
        researchTraces.length > 0 ? researchTraces : undefined,
        researchSourcesByRef.size > 0 ? flushSources() : undefined,
      );
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      // A stopped stream can finish after a newer turn starts: never reset it.
      if (abortRef.current === controller) {
        resetStream();
        abortRef.current = null;
      }
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Response: ${accumulatedContent.length} chars`,
      });
      if (chatRequestIdRef.current === chatRequestId) chatRequestIdRef.current = null;

      // Research path updates session counters optimistically from the
      // `done` event's usage payload — re-fetching here would overwrite
      // it with a potentially stale snapshot if the server's research
      // telemetry hasn't been merged into /v1/savings yet.
      if (!useResearch) {
        fetchSavings()
          .then((data) => useAppStore.getState().setSavings(data))
          .catch(() => {});
      }
    }
  }, [
    input,
    pendingFiles,
    activeId,
    selectedModel,
    streamState.isStreaming,
    createConversation,
    addMessage,
    updateLastAssistant,
    setStreamState,
    resetStream,
    deepResearch,
    temperature,
    maxTokens,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="px-4 pb-4 pt-2" style={{ maxWidth: 'var(--chat-max-width)', margin: '0 auto', width: '100%' }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes('Files')) {
          event.preventDefault();
          setDragActive(true);
        }
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setDragActive(false);
        }
      }}
      onDrop={(event) => {
        if (event.dataTransfer.files.length > 0) {
          event.preventDefault();
          setDragActive(false);
          if (!streamState.isStreaming && !uploadingFiles) {
            attachFiles(Array.from(event.dataTransfer.files));
          }
        }
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={CHAT_FILE_ACCEPT}
        className="hidden"
        aria-label="Attach files"
        onChange={(event) => {
          attachFiles(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
      <div className="mb-2 flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setDeepResearch(!deepResearch)}
            disabled={streamState.isStreaming}
            aria-pressed={deepResearch}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer disabled:cursor-default disabled:opacity-50"
            style={{
              background: deepResearch ? 'var(--color-accent-subtle)' : 'transparent',
              border: `1px solid ${deepResearch ? 'var(--color-accent)' : 'var(--color-border)'}`,
              color: deepResearch ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
            }}
            title={deepResearch ? 'Indexed personal data research: on. Public URLs open with Chat tools.' : 'Research your indexed Gmail and other personal data'}
          >
            <Search size={12} />
            Deep Research
          </button>
        </div>
        {deepResearch && (
          <div className="text-[11px] leading-snug" style={{ color: 'var(--color-text-tertiary)' }}>
            Deep Research searches connected personal data. External URLs use Chat tools.
          </div>
        )}
        {deepResearch && corpusSync.syncing && corpusSync.itemsSynced > 0 && (
          <div
            className="text-[11px] leading-snug"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Searching over{' '}
            <span key={corpusSync.itemsSynced} className="sync-bump" style={{ color: 'var(--color-text-secondary)' }}>
              {corpusSync.itemsSynced.toLocaleString()}
            </span>{' '}
            items — sync in progress, results will improve as more data is indexed.
          </div>
        )}
      </div>
      {pendingFiles.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2" aria-label="Pending attachments">
          {pendingFiles.map((file, index) => (
            <span key={`${file.name}-${index}`} className="inline-flex items-center gap-2 rounded-xl px-2.5 py-1.5 text-xs"
              style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
              <Paperclip size={12} />
              {file.name}
              <button type="button" title={`Remove ${file.name}`} aria-label={`Remove ${file.name}`}
                disabled={uploadingFiles}
                onClick={() => setPendingFiles((items) => items.filter((_, i) => i !== index))}>
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      {dragActive && (
        <div className="mb-2 rounded-xl border border-dashed p-3 text-center text-xs"
          style={{ borderColor: 'var(--color-accent)', color: 'var(--color-accent)' }}>
          Drop files to attach to this conversation
        </div>
      )}
      <div
        className="flex items-center gap-2 rounded-2xl px-4 py-3 transition-shadow"
        style={{
          background: 'var(--color-input-bg)',
          border: '1px solid var(--color-input-border)',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={selectedModel ? 'Message OpenJarvis...' : 'Pick a model first (⌘K)...'}
          rows={1}
          className="flex-1 bg-transparent outline-none resize-none text-sm leading-relaxed"
          style={{ color: 'var(--color-text)', maxHeight: '200px' }}
          disabled={streamState.isStreaming || uploadingFiles || modelLoading}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={streamState.isStreaming || uploadingFiles || modelLoading}
          title="Attach files (PDF, DOCX, TXT, code)"
          aria-label="Attach files"
          className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer disabled:opacity-30"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <Paperclip size={17} />
        </button>
        {isCurrentChatStreaming ? (
          <button
            onClick={stopStreaming}
            className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer"
            style={{ background: 'var(--color-error)', color: 'var(--color-on-accent)' }}
            title="Stop generating"
          >
            <Square size={16} />
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <MicButton
              state={speechState}
              onClick={handleMicClick}
              disabled={micDisabled}
              reason={micReason}
            />
            <button
              onClick={sendMessage}
              disabled={streamState.isStreaming || uploadingFiles || (!input.trim() && pendingFiles.length === 0) || modelLoading || !selectedModel}
              title={selectedModel ? 'Send message' : 'Pick a model first (⌘K)'}
              className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background: (input.trim() || pendingFiles.length) ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: (input.trim() || pendingFiles.length) ? 'white' : 'var(--color-text-tertiary)',
              }}
            >
              {uploadingFiles ? <span className="text-xs">Reading...</span> : <Send size={16} />}
            </button>
          </div>
        )}
      </div>
      <div className="flex items-center justify-center mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>
          <kbd className="font-mono">Enter</kbd> to send &middot;{' '}
          <kbd className="font-mono">Shift+Enter</kbd> for new line
        </span>
      </div>
    </div>
  );
}
