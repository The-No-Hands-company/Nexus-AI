import React, { useState, useEffect } from 'react';

function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [imagePrompt, setImagePrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneratingImage, setIsGeneratingImage] = useState(false);

  const [skills, setSkills] = useState([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState(null);
  const [selectedSkill, setSelectedSkill] = useState(null);
  const [skillTaskInput, setSkillTaskInput] = useState('');
  const [skillResult, setSkillResult] = useState(null);
  const [skillRunning, setSkillRunning] = useState(false);
  const [skillRunError, setSkillRunError] = useState(null);

  const [sprintTask, setSprintTask] = useState('');
  const [sprintSkills, setSprintSkills] = useState('');
  const [sprintRunning, setSprintRunning] = useState(false);
  const [sprintResult, setSprintResult] = useState(null);
  const [sprintError, setSprintError] = useState(null);

  const [suggestTask, setSuggestTask] = useState('');
  const [suggestResult, setSuggestResult] = useState(null);
  const [suggestLoading, setSuggestLoading] = useState(false);

  const fetchSkills = async () => {
    setSkillsLoading(true);
    setSkillsError(null);
    try {
      const response = await fetch('/nostack/skills');
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      setSkills(Array.isArray(data) ? data : data.skills || []);
    } catch (error) {
      setSkillsError(error.message);
    } finally {
      setSkillsLoading(false);
    }
  };

  const runSkill = async () => {
    if (!skillTaskInput.trim() || !selectedSkill) return;
    setSkillRunning(true);
    setSkillRunError(null);
    setSkillResult(null);
    try {
      const response = await fetch(`/nostack/skills/${selectedSkill.name}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: skillTaskInput })
      });
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      setSkillResult(data);
    } catch (error) {
      setSkillRunError(error.message);
    } finally {
      setSkillRunning(false);
    }
  };

  const classifyTask = async () => {
    if (!suggestTask.trim()) return;
    setSuggestLoading(true);
    setSuggestResult(null);
    try {
      const response = await fetch('/nostack/skills/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: suggestTask })
      });
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      setSuggestResult(data);
    } catch (error) {
      setSuggestResult({ error: error.message });
    } finally {
      setSuggestLoading(false);
    }
  };

  const runSprint = async () => {
    if (!sprintTask.trim() || !sprintSkills.trim()) return;
    setSprintRunning(true);
    setSprintError(null);
    setSprintResult(null);
    try {
      const response = await fetch('/nostack/sprint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: sprintTask,
          skills: sprintSkills.split(',').map(s => s.trim()).filter(Boolean)
        })
      });
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      setSprintResult(data);
    } catch (error) {
      setSprintError(error.message);
    } finally {
      setSprintRunning(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'team' && skills.length === 0 && !skillsLoading && !skillsError) {
      fetchSkills();
    }
  }, [activeTab]);

  const sendMessage = async () => {
    if (!input.trim()) return;

    const userMessage = {
      id: Date.now(),
      text: input,
      sender: 'user',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: 'nexus-ai/auto',
          messages: [
            {
              role: 'user',
              content: input
            }
          ],
          stream: false
        })
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const data = await response.json();
      const aiMessage = {
        id: Date.now() + 1,
        text: data.choices[0].message.content,
        sender: 'assistant',
        timestamp: new Date()
      };

      setMessages(prev => [...prev, aiMessage]);
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage = {
        id: Date.now() + 1,
        text: `Sorry, I encountered an error: ${error.message}`,
        sender: 'assistant',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const generateImage = async () => {
    if (!imagePrompt.trim()) return;

    setIsGeneratingImage(true);
    
    try {
      const response = await fetch('/v1/agent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          task: `Generate an image of: ${imagePrompt}`,
          stream: false
        })
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const data = await response.json();
      
      const aiMessage = {
        id: Date.now() + 1,
        text: data.result || 'Image generated successfully',
        sender: 'assistant',
        timestamp: new Date(),
        isImage: true,
        imageData: data.result
      };

      setMessages(prev => [...prev, aiMessage]);
    } catch (error) {
      console.error('Error generating image:', error);
      const errorMessage = {
        id: Date.now() + 1,
        text: `Sorry, I encountered an error generating the image: ${error.message}`,
        sender: 'assistant',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsGeneratingImage(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (e.target.placeholder.includes('image')) {
        generateImage();
      } else {
        sendMessage();
      }
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Nexus AI Assistant</h1>
        <div className="header-tabs">
          <button
            className={`header-tab ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            Chat
          </button>
          <button
            className={`header-tab ${activeTab === 'image' ? 'active' : ''}`}
            onClick={() => setActiveTab('image')}
          >
            Image
          </button>
          <button
            className={`header-tab ${activeTab === 'team' ? 'active' : ''}`}
            onClick={() => setActiveTab('team')}
          >
            Team
          </button>
        </div>
      </header>
      <main>
        {(activeTab === 'chat' || activeTab === 'image') && (
          <div className="chat-container">
            <div className="chat-messages">
              {messages.map(message => (
                <div 
                  key={message.id} 
                  className={`message ${message.sender} ${message.isImage ? 'image-message' : ''}`}
                >
                  <div className="message-content">
                    {message.isImage ? (
                      <>
                        <img 
                          src={`data:image/png;base64,${message.imageData}`} 
                          alt="Generated image"
                          className="generated-image"
                        />
                        <p>{message.text}</p>
                      </>
                    ) : (
                      <>
                        <p>{message.text}</p>
                        {message.timestamp && <small className="message-time">
                          {message.timestamp.toLocaleTimeString()}
                        </small>}
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="chat-input-container">
              {activeTab === 'chat' ? (
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Type a message to Nexus AI..."
                  rows={2}
                  disabled={isLoading}
                />
              ) : (
                <input
                  type="text"
                  value={imagePrompt}
                  onChange={(e) => setImagePrompt(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Describe the image you want to generate..."
                  disabled={isGeneratingImage}
                />
              )}
              
              <div className="button-group">
                {activeTab === 'chat' ? (
                  <button 
                    onClick={sendMessage}
                    disabled={isLoading || !input.trim()}
                  >
                    {isLoading ? 'Sending...' : 'Send'}
                  </button>
                ) : (
                  <button 
                    onClick={generateImage}
                    disabled={isGeneratingImage || !imagePrompt.trim()}
                  >
                    {isGeneratingImage ? 'Generating...' : 'Generate Image'}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'team' && (
          <div className="team-container">
            <div className="sprint-section" style={{ marginBottom: '1.5rem', padding: '1rem', borderRadius: '8px', background: 'var(--surface2)', border: '1px solid var(--border)' }}>
              <h2 style={{ margin: '0 0 0.25rem', fontSize: '0.9rem' }}>Suggest Skills</h2>
              <p className="section-desc" style={{ margin: '0 0 0.5rem' }}>Describe your task and get skill recommendations.</p>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  type="text"
                  value={suggestTask}
                  onChange={(e) => setSuggestTask(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && classifyTask()}
                  placeholder="e.g. audit my codebase for security..."
                  disabled={suggestLoading}
                  style={{ flex: 1, padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', fontSize: '0.85rem' }}
                />
                <button onClick={classifyTask} disabled={suggestLoading || !suggestTask.trim()}
                  style={{ padding: '0.5rem 1rem', borderRadius: '6px', border: 'none', background: '#6366f1', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem' }}>
                  {suggestLoading ? '…' : 'Suggest'}
                </button>
              </div>
              {suggestResult && !suggestResult.error && (
                <div style={{ marginTop: '0.5rem' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                    {suggestResult.skills?.map(s => (
                      <span key={s.command} onClick={() => { setSelectedSkill(s); setSkillTaskInput(''); }}
                        style={{ padding: '0.25rem 0.6rem', borderRadius: '12px', background: 'var(--surface)', border: '1px solid var(--border)', fontSize: '0.75rem', cursor: 'pointer' }}>
                        {s.command} ({s.score})
                      </span>
                    ))}
                  </div>
                  {suggestResult.suggested_template && (
                    <div style={{ marginTop: '0.35rem', fontSize: '0.7rem', color: 'var(--muted)' }}>
                      Template: <b>{suggestResult.suggested_template}</b> → {suggestResult.sprint_template?.map(s => '/' + s).join(', ')}
                    </div>
                  )}
                </div>
              )}
              {suggestResult?.error && <div style={{ marginTop: '0.35rem', fontSize: '0.75rem', color: 'var(--red)' }}>{suggestResult.error}</div>}
            </div>
            <div className="sprint-section">
              <h2>Run Sprint</h2>
              <p className="section-desc">Orchestrate multiple skills to complete a complex task.</p>
              <textarea
                className="sprint-input"
                value={sprintTask}
                onChange={(e) => setSprintTask(e.target.value)}
                placeholder="Describe the task..."
                rows={2}
                disabled={sprintRunning}
              />
              <input
                type="text"
                className="sprint-input"
                value={sprintSkills}
                onChange={(e) => setSprintSkills(e.target.value)}
                placeholder="Skills (comma-separated, e.g. architect, coder, reviewer)"
                disabled={sprintRunning}
              />
              <button
                className="sprint-btn"
                onClick={runSprint}
                disabled={sprintRunning || !sprintTask.trim() || !sprintSkills.trim()}
              >
                {sprintRunning ? 'Running Sprint...' : 'Run Sprint'}
              </button>
              {sprintError && <div className="error-message">{sprintError}</div>}
              {sprintResult && (
                <div className="result-panel">
                  <pre>{JSON.stringify(sprintResult, null, 2)}</pre>
                </div>
              )}
            </div>

            <div className="skills-section">
              <h2>Available Skills</h2>
              {skillsLoading && <div className="loading">Loading skills...</div>}
              {skillsError && <div className="error-message">{skillsError}</div>}
              {!skillsLoading && !skillsError && skills.length === 0 && (
                <p className="no-skills">No skills found.</p>
              )}
              {!skillsLoading && !skillsError && (
                <div className="skills-grid">
                  {skills.map(skill => (
                    <div
                      key={skill.name}
                      className="skill-card"
                      onClick={() => {
                        setSelectedSkill(skill);
                        setSkillTaskInput('');
                        setSkillResult(null);
                        setSkillRunError(null);
                      }}
                    >
                      <div className="skill-card-header">
                        <h3>{skill.name}</h3>
                        {skill.command && <code className="skill-command">{skill.command}</code>}
                      </div>
                      {skill.description && <p className="skill-desc">{skill.description}</p>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {selectedSkill && (
              <div className="modal-overlay" onClick={() => { setSelectedSkill(null); }}>
                <div className="modal-content" onClick={e => e.stopPropagation()}>
                  <div className="modal-header">
                    <h2>{selectedSkill.name}</h2>
                    <button className="modal-close" onClick={() => { setSelectedSkill(null); }}>&times;</button>
                  </div>
                  {selectedSkill.command && (
                    <code className="modal-command">{selectedSkill.command}</code>
                  )}
                  {selectedSkill.description && (
                    <p className="modal-desc">{selectedSkill.description}</p>
                  )}
                  <textarea
                    className="modal-input"
                    value={skillTaskInput}
                    onChange={(e) => setSkillTaskInput(e.target.value)}
                    placeholder="Enter your task..."
                    rows={3}
                    disabled={skillRunning}
                  />
                  <div className="modal-buttons">
                    <button
                      className="btn-primary"
                      onClick={runSkill}
                      disabled={skillRunning || !skillTaskInput.trim()}
                    >
                      {skillRunning ? 'Running...' : 'Run'}
                    </button>
                    <button
                      className="btn-secondary"
                      onClick={() => { setSelectedSkill(null); }}
                    >
                      Cancel
                    </button>
                  </div>
                  {skillRunError && <div className="error-message">{skillRunError}</div>}
                  {skillResult && (
                    <div className="result-panel">
                      <pre>{JSON.stringify(skillResult, null, 2)}</pre>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App
