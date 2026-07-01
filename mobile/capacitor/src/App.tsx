import { useState, useEffect, useRef, useCallback } from 'react';
import { Camera, CameraResultType, CameraSource, Photo } from '@capacitor/camera';
import { Filesystem, Directory, Encoding } from '@capacitor/filesystem';
import { LocalNotifications, ScheduleOptions } from '@capacitor/local-notifications';
import { Share } from '@capacitor/share';
import { Preferences } from '@capacitor/preferences';
import { Keyboard, KeyboardInfo } from '@capacitor/keyboard';
import { StatusBar, Style } from '@capacitor/status-bar';
import { SplashScreen } from '@capacitor/splash-screen';

const DEFAULT_BACKEND = 'http://localhost:8000';

interface Message {
  id: string;
  text: string;
  sender: 'user' | 'assistant' | 'system';
  timestamp: Date;
  isImage?: boolean;
  imageData?: string;
}

interface GeneratedImage {
  id: string;
  data: string;
  timestamp: number;
  prompt: string;
}

interface NostackSkill {
  id: string;
  command: string;
  name: string;
  description: string;
}

/** Descriptive error wrapper for Capacitor plugin failures. */
function fmtPluginError(action: string, err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  return `${action}: ${msg || 'unknown plugin error'}`;
}

export default function NexusAIMobileApp() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [generatedImages, setGeneratedImages] = useState<GeneratedImage[]>([]);
  const [notifications, setNotifications] = useState<{ id: string; title: string; body: string; timestamp: number }[]>([]);
  const [userPreferences, setUserPreferences] = useState({
    theme: 'dark',
    notificationsEnabled: true,
    autoSave: true,
    backendUrl: DEFAULT_BACKEND,
  });
  const [activeTab, setActiveTab] = useState<'chat' | 'skills' | 'images' | 'settings'>('chat');
  const [nostackSkills, setNostackSkills] = useState<NostackSkill[]>([]);
  const [selectedSkill, setSelectedSkill] = useState('');
  const [skillTask, setSkillTask] = useState('');
  const [isKeyboardVisible, setIsKeyboardVisible] = useState(false);
  const [keyboardHeight, setKeyboardHeight] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const backendUrl = userPreferences.backendUrl || DEFAULT_BACKEND;

  // ── lifecycle ──────────────────────────────────────────────────────

  useEffect(() => {
    initializeApp();
    return () => {
      wsRef.current?.close();
    };
  }, []);

  /** Scroll chat to bottom when messages change. */
  useEffect(() => {
    chatEndRef.current?.scrollTo({ top: chatEndRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const initializeApp = async () => {
    try {
      // Hide splash screen as soon as the app is ready
      await SplashScreen.hide();

      // Restore persisted preferences
      const savedPrefs = await Preferences.get({ key: 'user_preferences' });
      if (savedPrefs.value) {
        setUserPreferences(JSON.parse(savedPrefs.value));
      }

      // Status bar: light overlays on dark background
      await StatusBar.setStyle({ style: Style.Light });
      await StatusBar.setBackgroundColor({ color: '#0a0f1a' });

      // Request notification permission (silently fails if denied)
      await requestNotificationPermission();

      await loadSavedData();
      await loadSkills();
      connectWebSocket();
    } catch (error) {
      console.error('Init failed:', error);
    }
  };

  // ═══════════════════════════════════════════════════════════════════
  //  CAMERA
  // ═══════════════════════════════════════════════════════════════════

  const capturePhoto = useCallback(async () => {
    try {
      const photo: Photo = await Camera.getPhoto({
        quality: 85,
        allowEditing: true,
        resultType: CameraResultType.Base64,
        source: CameraSource.Prompt,
        saveToGallery: false,
      });

      if (!photo.base64String) {
        addSystemMessage('Camera did not return image data.');
        return;
      }

      // Optionally save to local filesystem
      const fileName = `captured_${Date.now()}.jpg`;
      await Filesystem.writeFile({
        path: `camera/${fileName}`,
        data: photo.base64String,
        directory: Directory.Documents,
      });

      const dataUrl = `data:image/jpeg;base64,${photo.base64String}`;
      addSystemMessage('Photo captured! Send a prompt to describe or use it with the AI.', dataUrl);
    } catch (error: any) {
      // User cancellation is not really an error
      if (error?.message?.includes('cancel') || error?.message?.includes('Cancelled')) {
        return;
      }
      addSystemMessage(fmtPluginError('Camera', error));
    }
  }, []);

  // ═══════════════════════════════════════════════════════════════════
  //  LOCAL NOTIFICATIONS
  // ═══════════════════════════════════════════════════════════════════

  const requestNotificationPermission = useCallback(async () => {
    try {
      const result = await LocalNotifications.requestPermissions();
      if (result.display !== 'granted') {
        console.warn('Notification permission not granted');
      }
    } catch {
      // Not supported on web; silently ignore
    }
  }, []);

  const scheduleNotification = useCallback(
    async (title: string, body: string, delayMs = 1000) => {
      if (!userPreferences.notificationsEnabled) return;
      try {
        const options: ScheduleOptions = {
          notifications: [
            {
              id: Date.now(),
              title,
              body,
              schedule: { at: new Date(Date.now() + delayMs) },
              actionTypeId: '',
              extra: null,
            },
          ],
        };
        await LocalNotifications.schedule(options);

        setNotifications((prev) => [
          { id: String(Date.now()), title, body, timestamp: Date.now() },
          ...prev.slice(0, 49), // keep last 50
        ]);
      } catch {
        // Silently ignore — notifications are best-effort
      }
    },
    [userPreferences.notificationsEnabled],
  );

  // ═══════════════════════════════════════════════════════════════════
  //  SHARE
  // ═══════════════════════════════════════════════════════════════════

  const shareImage = useCallback(async (image: GeneratedImage) => {
    try {
      await Share.share({
        title: 'Share AI-generated image',
        text: `Created with Nexus AI — "${image.prompt}"`,
        url: image.data,
        dialogTitle: 'Share via',
      });
    } catch (error: any) {
      if (error?.message?.includes('cancel') || error?.message?.includes('Cancelled')) return;
      addSystemMessage(fmtPluginError('Share', error));
    }
  }, []);

  // ═══════════════════════════════════════════════════════════════════
  //  KEYBOARD
  // ═══════════════════════════════════════════════════════════════════

  useEffect(() => {
    const onShow = (info: KeyboardInfo) => {
      setIsKeyboardVisible(true);
      setKeyboardHeight(info.keyboardHeight);
    };
    const onHide = () => {
      setIsKeyboardVisible(false);
      setKeyboardHeight(0);
    };

    Keyboard.addListener('keyboardWillShow', onShow);
    Keyboard.addListener('keyboardWillHide', onHide);

    return () => {
      Keyboard.removeAllListeners();
    };
  }, []);

  // ═══════════════════════════════════════════════════════════════════
  //  FILESYSTEM
  // ═══════════════════════════════════════════════════════════════════

  const loadSavedData = async () => {
    try {
      const imgData = await Filesystem.readFile({
        path: 'generated_images.json',
        directory: Directory.Documents,
        encoding: Encoding.UTF8,
      });
      if (imgData.data) {
        const parsed: GeneratedImage[] = JSON.parse(imgData.data as string);
        setGeneratedImages(parsed);
      }
    } catch {
      // No saved data yet — fine
    }
  };

  const saveData = async () => {
    if (!userPreferences.autoSave) return;
    try {
      await Filesystem.writeFile({
        path: 'generated_images.json',
        data: JSON.stringify(generatedImages),
        directory: Directory.Documents,
        encoding: Encoding.UTF8,
      });
    } catch {
      // Best-effort persistence
    }
  };

  // ═══════════════════════════════════════════════════════════════════
  //  SKILLS & WS
  // ═══════════════════════════════════════════════════════════════════

  const loadSkills = async () => {
    try {
      const resp = await fetch(`${backendUrl}/nostack/skills`);
      if (resp.ok) {
        const data = await resp.json();
        setNostackSkills(data.skills || []);
      }
    } catch {
      // Backend may not be available
    }
  };

  const connectWebSocket = () => {
    try {
      const wsUrl = backendUrl.replace(/^http/, 'ws') + '/collab/rooms/mobile/ws';
      const ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.content) {
            setMessages((prev) => [
              ...prev,
              { id: Date.now().toString(), text: msg.content, sender: 'assistant', timestamp: new Date() },
            ]);
          }
        } catch {
          // ignore malformed WS messages
        }
      };
      ws.onclose = () => {
        setTimeout(connectWebSocket, 3000);
      };
      wsRef.current = ws;
    } catch {
      // WS not available
    }
  };

  // ═══════════════════════════════════════════════════════════════════
  //  MESSAGING HELPERS
  // ═══════════════════════════════════════════════════════════════════

  const addSystemMessage = (text: string, imageData?: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: String(Date.now()),
        text,
        sender: 'system',
        timestamp: new Date(),
        isImage: !!imageData,
        imageData,
      },
    ]);
  };

  // ═══════════════════════════════════════════════════════════════════
  //  API CALLS
  // ═══════════════════════════════════════════════════════════════════

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMsg: Message = { id: String(Date.now()), text: input, sender: 'user', timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    const prompt = input;
    setInput('');
    setIsLoading(true);
    try {
      const resp = await fetch(`${backendUrl}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'nexus-ai/auto',
          messages: [{ role: 'user', content: prompt }],
          stream: false,
        }),
      });
      if (!resp.ok) throw new Error(`API error: ${resp.status}`);
      const data = await resp.json();
      const text = data.choices?.[0]?.message?.content || 'No response';

      setMessages((prev) => [
        ...prev,
        { id: String(Date.now() + 1), text, sender: 'assistant', timestamp: new Date() },
      ]);

      // Schedule a notification for proactive agent results
      if (text.length > 20) {
        await scheduleNotification('Nexus AI Response', text.substring(0, 80) + '…');
      }
    } catch (error: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: String(Date.now() + 2),
          text: `Error: ${error.message || 'Unknown error'}`,
          sender: 'system',
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const runSkill = async (skillName: string) => {
    if (!skillTask.trim()) return;
    setIsLoading(true);
    try {
      const resp = await fetch(`${backendUrl}/nostack/skills/${skillName}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: skillTask }),
      });
      const data = await resp.json();
      setMessages((prev) => [
        ...prev,
        { id: String(Date.now()), text: `/${skillName}: ${skillTask}`, sender: 'user', timestamp: new Date() },
        {
          id: String(Date.now() + 1),
          text: data.result || data.error || 'No result',
          sender: 'assistant',
          timestamp: new Date(),
        },
      ]);
      setSkillTask('');
      setSelectedSkill('');

      await scheduleNotification(`Skill /${skillName} complete`, data.result?.substring?.(0, 80) || 'Done');
    } catch (error: any) {
      setMessages((prev) => [
        ...prev,
        { id: String(Date.now() + 2), text: `Skill error: ${error.message}`, sender: 'system', timestamp: new Date() },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const generateImage = async () => {
    setIsLoading(true);
    try {
      const resp = await fetch(`${backendUrl}/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: input || 'Generate a beautiful image',
          action: 'image_gen',
          backend: 'pollinations',
        }),
      });
      if (!resp.ok) throw new Error(`API error: ${resp.status}`);
      const data = await resp.json();
      const img: GeneratedImage = {
        id: String(Date.now()),
        data: data.result || '',
        timestamp: Date.now(),
        prompt: input,
      };
      setGeneratedImages((prev) => [...prev, img]);
      setMessages((prev) => [
        ...prev,
        {
          id: String(Date.now() + 3),
          text: 'Image generated!',
          sender: 'assistant',
          timestamp: new Date(),
          isImage: true,
          imageData: data.result,
        },
      ]);
      await saveData();
      await scheduleNotification('Image Generated', `"${img.prompt?.substring(0, 60) || 'Creation'}" is ready.`);
    } catch (error: any) {
      setMessages((prev) => [
        ...prev,
        { id: String(Date.now() + 4), text: `Image error: ${error.message}`, sender: 'system', timestamp: new Date() },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const updatePreferences = async (newPrefs: Partial<typeof userPreferences>) => {
    const updated = { ...userPreferences, ...newPrefs };
    setUserPreferences(updated);
    await Preferences.set({ key: 'user_preferences', value: JSON.stringify(updated) });
  };

  // ═══════════════════════════════════════════════════════════════════
  //  RENDER
  // ═══════════════════════════════════════════════════════════════════

  const inputAreaPadding = isKeyboardVisible ? keyboardHeight : 0;

  return (
    <div
      className="App"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        background: '#0a0f1a',
        color: '#e0e0e0',
        paddingBottom: inputAreaPadding,
      }}
    >
      {/* ── Header ──────────────────────────────────────────────────── */}
      <header
        style={{
          padding: '10px 16px',
          background: 'linear-gradient(135deg, #1e293b, #0f172a)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #334155',
        }}
      >
        <h1 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 600 }}>Nexus AI</h1>
        <div style={{ display: 'flex', gap: '6px' }}>
          {(['chat', 'skills', 'images', 'settings'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: '6px 12px',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                background: activeTab === tab ? '#6366f1' : '#1f2937',
                color: '#e0e0e0',
                fontSize: '0.85rem',
                fontWeight: activeTab === tab ? 600 : 400,
              }}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
      </header>

      {/* ── Main Content ────────────────────────────────────────────── */}
      <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {/* ── CHAT TAB ───────────────────────────────────────────────── */}
        {activeTab === 'chat' && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div
              ref={chatEndRef}
              style={{
                flex: 1,
                overflow: 'auto',
                padding: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  style={{
                    padding: '8px 14px',
                    borderRadius: '12px',
                    background: msg.sender === 'user' ? '#6366f1' : msg.sender === 'system' ? '#991b1b' : '#1f2937',
                    alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '85%',
                    border:
                      msg.sender === 'assistant' ? '1px solid #374151' : 'none',
                  }}
                >
                  {msg.isImage && msg.imageData ? (
                    <img
                      src={msg.imageData}
                      alt="Generated"
                      style={{ maxWidth: '100%', borderRadius: '8px', marginBottom: '6px' }}
                    />
                  ) : null}
                  <p style={{ margin: 0, lineHeight: 1.4 }}>{msg.text}</p>
                  <small style={{ opacity: 0.5, fontSize: '0.7rem' }}>
                    {msg.timestamp.toLocaleTimeString()}
                  </small>
                </div>
              ))}
              {isLoading && (
                <p style={{ opacity: 0.5, textAlign: 'center', padding: '8px' }}>Loading…</p>
              )}
            </div>

            {/* Input bar */}
            <div
              style={{
                padding: '8px',
                display: 'flex',
                gap: '6px',
                background: '#111827',
                borderTop: '1px solid #334155',
              }}
            >
              <button
                onClick={capturePhoto}
                disabled={isLoading}
                title="Take photo"
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: '1px solid #374151',
                  background: '#1f2937',
                  color: '#e0e0e0',
                  cursor: 'pointer',
                  fontSize: '1.1rem',
                }}
              >
                📷
              </button>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
                placeholder="Ask Nexus AI…"
                disabled={isLoading}
                style={{
                  flex: 1,
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: '1px solid #374151',
                  background: '#1f2937',
                  color: '#e0e0e0',
                  fontSize: '0.95rem',
                }}
              />
              <button
                onClick={sendMessage}
                disabled={isLoading || !input.trim()}
                style={{
                  padding: '10px 16px',
                  borderRadius: '8px',
                  border: 'none',
                  background: '#6366f1',
                  color: '#fff',
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
              >
                Send
              </button>
              <button
                onClick={generateImage}
                disabled={isLoading}
                title="Generate image from prompt"
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: 'none',
                  background: '#8b5cf6',
                  color: '#fff',
                  cursor: 'pointer',
                  fontSize: '1.1rem',
                }}
              >
                🎨
              </button>
            </div>
          </div>
        )}

        {/* ── SKILLS TAB ─────────────────────────────────────────────── */}
        {activeTab === 'skills' && (
          <div style={{ padding: '12px', overflow: 'auto', height: '100%' }}>
            <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem' }}>Virtual Team Skills</h2>
            {nostackSkills.length === 0 && (
              <p style={{ opacity: 0.5 }}>No skills loaded. Connect to a Nexus AI backend to see available skills.</p>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {nostackSkills.map((skill) => (
                <button
                  key={skill.id}
                  onClick={() => {
                    setSelectedSkill(skill.command.replace('/', ''));
                    setSkillTask('');
                  }}
                  style={{
                    padding: '12px',
                    borderRadius: '8px',
                    border: '1px solid #374151',
                    background: selectedSkill === skill.command.replace('/', '') ? '#1f2937' : 'transparent',
                    color: '#e0e0e0',
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  <strong>{skill.name}</strong>
                  <p style={{ margin: '4px 0 0', opacity: 0.7, fontSize: '0.85rem' }}>{skill.description}</p>
                  <code style={{ opacity: 0.5, fontSize: '0.8rem' }}>{skill.command}</code>
                </button>
              ))}
            </div>
            {selectedSkill && (
              <div style={{ marginTop: '12px', padding: '12px', borderRadius: '8px', background: '#1f2937' }}>
                <h3 style={{ margin: '0 0 8px' }}>Run /{selectedSkill}</h3>
                <textarea
                  value={skillTask}
                  onChange={(e) => setSkillTask(e.target.value)}
                  placeholder={`What should /${selectedSkill} work on?`}
                  rows={3}
                  disabled={isLoading}
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '8px',
                    border: '1px solid #374151',
                    background: '#111827',
                    color: '#e0e0e0',
                    resize: 'vertical',
                    fontSize: '0.95rem',
                    boxSizing: 'border-box',
                  }}
                />
                <button
                  onClick={() => runSkill(selectedSkill)}
                  disabled={isLoading || !skillTask.trim()}
                  style={{
                    marginTop: '8px',
                    padding: '10px 20px',
                    borderRadius: '8px',
                    border: 'none',
                    background: '#6366f1',
                    color: '#fff',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  Run /{selectedSkill}
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── IMAGES TAB ─────────────────────────────────────────────── */}
        {activeTab === 'images' && (
          <div style={{ padding: '12px', overflow: 'auto', height: '100%' }}>
            <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem' }}>Generated Images</h2>
            {generatedImages.length === 0 && (
              <p style={{ opacity: 0.5 }}>No images yet. Use the 🎨 button in the Chat tab to generate one.</p>
            )}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
                gap: '10px',
              }}
            >
              {generatedImages.map((img) => (
                <div
                  key={img.id}
                  style={{
                    borderRadius: '8px',
                    overflow: 'hidden',
                    background: '#1f2937',
                    border: '1px solid #374151',
                  }}
                >
                  <img
                    src={img.data}
                    alt={img.prompt}
                    style={{ width: '100%', aspectRatio: '1', objectFit: 'cover' }}
                  />
                  <p style={{ padding: '4px 8px', margin: 0, fontSize: '0.75rem', opacity: 0.7, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {img.prompt.substring(0, 50)}
                  </p>
                  <button
                    onClick={() => shareImage(img)}
                    style={{
                      width: '100%',
                      padding: '8px',
                      border: 'none',
                      background: '#4338ca',
                      color: '#fff',
                      cursor: 'pointer',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                    }}
                  >
                    Share
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── SETTINGS TAB ───────────────────────────────────────────── */}
        {activeTab === 'settings' && (
          <div style={{ padding: '12px', overflow: 'auto', height: '100%' }}>
            <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem' }}>Settings</h2>

            <label
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '12px 0',
                borderBottom: '1px solid #374151',
              }}
            >
              Backend URL
              <input
                value={userPreferences.backendUrl}
                onChange={(e) => updatePreferences({ backendUrl: e.target.value })}
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  border: '1px solid #374151',
                  background: '#1f2937',
                  color: '#e0e0e0',
                  width: '200px',
                  fontSize: '0.9rem',
                }}
              />
            </label>

            <label
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '12px 0',
                borderBottom: '1px solid #374151',
              }}
            >
              Enable Notifications
              <input
                type="checkbox"
                checked={userPreferences.notificationsEnabled}
                onChange={(e) => updatePreferences({ notificationsEnabled: e.target.checked })}
                style={{ width: '20px', height: '20px', accentColor: '#6366f1' }}
              />
            </label>

            <label
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '12px 0',
                borderBottom: '1px solid #374151',
              }}
            >
              Auto-save Images
              <input
                type="checkbox"
                checked={userPreferences.autoSave}
                onChange={(e) => updatePreferences({ autoSave: e.target.checked })}
                style={{ width: '20px', height: '20px', accentColor: '#6366f1' }}
              />
            </label>

            {/* Notifications log */}
            {notifications.length > 0 && (
              <div style={{ marginTop: '16px' }}>
                <h3 style={{ margin: '0 0 8px', fontSize: '1rem' }}>Recent Notifications</h3>
                {notifications.slice(0, 10).map((n) => (
                  <div
                    key={n.id}
                    style={{
                      padding: '8px 12px',
                      marginBottom: '6px',
                      borderRadius: '8px',
                      background: '#1f2937',
                      border: '1px solid #374151',
                    }}
                  >
                    <strong style={{ fontSize: '0.85rem' }}>{n.title}</strong>
                    <p style={{ margin: '2px 0 0', opacity: 0.7, fontSize: '0.8rem' }}>{n.body}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
