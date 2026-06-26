import React, { useState } from 'react';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [imagePrompt, setImagePrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneratingImage, setIsGeneratingImage] = useState(false);

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
      // Call Nexus AI backend API
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
      // Call Nexus AI agent API for image generation
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
      
      // Add the generated image to the chat
      const aiMessage = {
        id: Date.now() + 1,
        text: data.result || 'Image generated successfully',
        sender: 'assistant',
        timestamp: new Date(),
        isImage: true,
        imageData: data.result // This would contain the base64 image data
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
      </header>
      <main>
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
            <div className="input-tabs">
              <button 
                className={`tab-button ${!isGeneratingImage ? 'active' : ''}`}
                onClick={() => setIsGeneratingImage(false)}
              >
                Chat
              </button>
              <button 
                className={`tab-button ${isGeneratingImage ? 'active' : ''}`}
                onClick={() => setIsGeneratingImage(true)}
              >
                Generate Image
              </button>
            </div>
            
            {!isGeneratingImage ? (
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
              {!isGeneratingImage ? (
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
      </main>
    </div>
  );
}

export default App