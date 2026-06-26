import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Camera, CameraResultType } from '@capacitor/camera';
import { Filesystem, Directory, Encoding } from '@capacitor/filesystem';
import { LocalNotifications } from '@capacitor/local-notifications';
import { Share } from '@capacitor/share';
import { Preferences } from '@capacitor/preferences';
import { Keyboard } from '@capacitor/keyboard';
import { StatusBar } from '@capacitor/status-bar';

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

export default function NexusAIMobileApp() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [generatedImages, setGeneratedImages] = useState<GeneratedImage[]>([]);
  const [notifications, setNotifications] = useState<{id: string; title: string; body: string; timestamp: number}[]>([]);
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

  const wsRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const backendUrl = userPreferences.backendUrl || DEFAULT_BACKEND;

  useEffect(() => {
    initializeApp();
    return () => { wsRef.current?.close(); };
  }, []);

  const initializeApp = async () => {
    try {
      const savedPrefs = await Preferences.get({ key: 'user_preferences' });
      if (savedPrefs.value) setUserPreferences(JSON.parse(savedPrefs.value));
      await StatusBar.setStyle({ style: 'LIGHT' });
      await StatusBar.setBackgroundColor({ color: '#0a0f1a' });
      await loadSavedData();
      await loadSkills();
      connectWebSocket();
    } catch (error) {
      console.error('Init failed:', error);
    }
  };

  const loadSavedData = async () => {
    try {
      const imgData = await Filesystem.readFile({
        path: 'generated_images.json', directory: Directory.Documents, encoding: Encoding.UTF8,
      });
      if (imgData.data) setGeneratedImages(JSON.parse(imgData.data as string));
    } catch {}
  };

  const saveData = async () => {
    if (!userPreferences.autoSave) return;
    try {
      await Filesystem.writeFile({
        path: 'generated_images.json', data: JSON.stringify(generatedImages),
        directory: Directory.Documents, encoding: Encoding.UTF8,
      });
    } catch {}
  };

  const loadSkills = async () => {
    try {
      const resp = await fetch(`${backendUrl}/nostack/skills`);
      if (resp.ok) {
        const data = await resp.json();
        setNostackSkills(data.skills || []);
      }
    } catch {}
  };

  const connectWebSocket = () => {
    try {
      const wsUrl = backendUrl.replace(/^http/, 'ws') + '/collab/rooms/mobile/ws';
      const ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.content) {
            setMessages(prev => [...prev, {
              id: Date.now().toString(), text: msg.content,
              sender: 'assistant', timestamp: new Date(),
            }]);
          }
        } catch {}
      };
      ws.onclose = () => { setTimeout(connectWebSocket, 3000); };
      wsRef.current = ws;
    } catch {}
  };

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMsg: Message = { id: Date.now().toString(), text: input, sender: 'user', timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);
    try {
      const resp = await fetch(`${backendUrl}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: 'nexus-ai/auto', messages: [{ role: 'user', content: input }], stream: false }),
      });
      if (!resp.ok) throw new Error(`API error: ${resp.status}`);
      const data = await resp.json();
      const text = data.choices?.[0]?.message?.content || 'No response';
      setMessages(prev => [...prev, { id: (Date.now() + 1).toString(), text, sender: 'assistant', timestamp: new Date() }]);
    } catch (error: any) {
      setMessages(prev => [...prev, { id: (Date.now() + 2).toString(), text: `Error: ${error.message}`, sender: 'system', timestamp: new Date() }]);
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
      setMessages(prev => [
        ...prev,
        { id: Date.now().toString(), text: `/${skillName}: ${skillTask}`, sender: 'user', timestamp: new Date() },
        { id: (Date.now() + 1).toString(), text: data.result || data.error || 'No result', sender: 'assistant', timestamp: new Date() },
      ]);
      setSkillTask('');
      setSelectedSkill('');
    } catch (error: any) {
      setMessages(prev => [...prev, { id: (Date.now() + 2).toString(), text: `Skill error: ${error.message}`, sender: 'system', timestamp: new Date() }]);
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
        body: JSON.stringify({ task: input || 'Generate a beautiful image', action: 'image_gen', backend: 'pollinations' }),
      });
      if (!resp.ok) throw new Error(`API error: ${resp.status}`);
      const data = await resp.json();
      const img: GeneratedImage = { id: Date.now().toString(), data: data.result || '', timestamp: Date.now(), prompt: input };
      setGeneratedImages(prev => [...prev, img]);
      setMessages(prev => [...prev, { id: (Date.now() + 3).toString(), text: 'Image generated!', sender: 'assistant', timestamp: new Date(), isImage: true, imageData: data.result }]);
      await saveData();
    } catch (error: any) {
      setMessages(prev => [...prev, { id: (Date.now() + 4).toString(), text: `Image error: ${error.message}`, sender: 'system', timestamp: new Date() }]);
    } finally {
      setIsLoading(false);
    }
  };

  const updatePreferences = async (newPrefs: Partial<typeof userPreferences>) => {
    const updated = { ...userPreferences, ...newPrefs };
    setUserPreferences(updated);
    await Preferences.set({ key: 'user_preferences', value: JSON.stringify(updated) });
  };

  return (
    <div className="App" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0a0f1a', color: '#e0e0e0' }}>
      <header style={{ padding: '12px 16px', background: '#111827', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1 style={{ margin: 0, fontSize: '1.2rem' }}>Nexus AI</h1>
        <div style={{ display: 'flex', gap: '8px' }}>
          {(['chat', 'skills', 'images', 'settings'] as const).map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              style={{ padding: '6px 12px', border: 'none', borderRadius: '6px', cursor: 'pointer',
                background: activeTab === tab ? '#6366f1' : '#1f2937', color: '#e0e0e0' }}>
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
      </header>

      <main style={{ flex: 1, overflow: 'hidden' }}>
        {activeTab === 'chat' && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ flex: 1, overflow: 'auto', padding: '12px' }} ref={chatEndRef}>
              {messages.map(msg => (
                <div key={msg.id} style={{ marginBottom: '8px', padding: '8px 12px', borderRadius: '8px',
                  background: msg.sender === 'user' ? '#6366f1' : msg.sender === 'system' ? '#991b1b' : '#1f2937',
                  alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%', marginLeft: msg.sender === 'user' ? 'auto' : '0' }}>
                  {msg.isImage && msg.imageData ? (
                    <img src={msg.imageData} alt="Generated" style={{ maxWidth: '100%', borderRadius: '8px', marginBottom: '4px' }} />
                  ) : null}
                  <p style={{ margin: 0 }}>{msg.text}</p>
                  <small style={{ opacity: 0.5 }}>{msg.timestamp.toLocaleTimeString()}</small>
                </div>
              ))}
              {isLoading && <p style={{ opacity: 0.5 }}>Loading...</p>}
            </div>
            <div style={{ padding: '8px', display: 'flex', gap: '8px', background: '#111827' }}>
              <input value={input} onChange={e => setInput(e.target.value)}
                onKeyPress={e => e.key === 'Enter' && sendMessage()}
                placeholder="Ask Nexus AI..." disabled={isLoading}
                style={{ flex: 1, padding: '10px', borderRadius: '8px', border: '1px solid #374151', background: '#1f2937', color: '#e0e0e0' }} />
              <button onClick={sendMessage} disabled={isLoading || !input.trim()}
                style={{ padding: '10px 16px', borderRadius: '8px', border: 'none', background: '#6366f1', color: '#fff', cursor: 'pointer' }}>
                Send
              </button>
              <button onClick={generateImage} disabled={isLoading}
                style={{ padding: '10px 16px', borderRadius: '8px', border: 'none', background: '#8b5cf6', color: '#fff', cursor: 'pointer' }}>
                Img
              </button>
            </div>
          </div>
        )}

        {activeTab === 'skills' && (
          <div style={{ padding: '12px', overflow: 'auto', height: '100%' }}>
            <h2>Virtual Team Skills</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {nostackSkills.map(skill => (
                <button key={skill.id} onClick={() => { setSelectedSkill(skill.command.replace('/','')); setSkillTask(''); }}
                  style={{ padding: '12px', borderRadius: '8px', border: '1px solid #374151', background: selectedSkill === skill.command.replace('/','') ? '#1f2937' : 'transparent', color: '#e0e0e0', textAlign: 'left', cursor: 'pointer' }}>
                  <strong>{skill.name}</strong>
                  <p style={{ margin: '4px 0 0', opacity: 0.7, fontSize: '0.85rem' }}>{skill.description}</p>
                  <code style={{ opacity: 0.5 }}>{skill.command}</code>
                </button>
              ))}
            </div>
            {selectedSkill && (
              <div style={{ marginTop: '12px', padding: '12px', borderRadius: '8px', background: '#1f2937' }}>
                <h3>Run /{selectedSkill}</h3>
                <textarea value={skillTask} onChange={e => setSkillTask(e.target.value)}
                  placeholder={`What should /${selectedSkill} work on?`}
                  rows={3} disabled={isLoading}
                  style={{ width: '100%', padding: '8px', borderRadius: '8px', border: '1px solid #374151', background: '#111827', color: '#e0e0e0', resize: 'vertical' }} />
                <button onClick={() => runSkill(selectedSkill)} disabled={isLoading || !skillTask.trim()}
                  style={{ marginTop: '8px', padding: '10px 20px', borderRadius: '8px', border: 'none', background: '#6366f1', color: '#fff', cursor: 'pointer' }}>
                  Run /{selectedSkill}
                </button>
              </div>
            )}
          </div>
        )}

        {activeTab === 'images' && (
          <div style={{ padding: '12px', overflow: 'auto', height: '100%' }}>
            <h2>Generated Images</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px' }}>
              {generatedImages.map(img => (
                <div key={img.id} style={{ borderRadius: '8px', overflow: 'hidden', background: '#1f2937' }}>
                  <img src={img.data} alt={img.prompt} style={{ width: '100%', aspectRatio: '1', objectFit: 'cover' }} />
                  <p style={{ padding: '4px 8px', fontSize: '0.8rem', opacity: 0.7 }}>{img.prompt.substring(0, 60)}</p>
                </div>
              ))}
              {generatedImages.length === 0 && <p style={{ opacity: 0.5 }}>No images yet. Generate one from the chat tab.</p>}
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div style={{ padding: '12px', overflow: 'auto', height: '100%' }}>
            <h2>Settings</h2>
            <label style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #374151' }}>
              Backend URL
              <input value={userPreferences.backendUrl} onChange={e => updatePreferences({ backendUrl: e.target.value })}
                style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #374151', background: '#1f2937', color: '#e0e0e0', width: '200px' }} />
            </label>
            <label style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #374151' }}>
              Notifications
              <input type="checkbox" checked={userPreferences.notificationsEnabled}
                onChange={e => updatePreferences({ notificationsEnabled: e.target.checked })} />
            </label>
            <label style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #374151' }}>
              Auto-save Images
              <input type="checkbox" checked={userPreferences.autoSave}
                onChange={e => updatePreferences({ autoSave: e.target.checked })} />
            </label>
          </div>
        )}
      </main>
    </div>
  );
}
