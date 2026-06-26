// The module 'vscode' contains the VS Code extensibility API
// Import the module and reference it with the alias vscode in your code below
const vscode = require('vscode');
const https = require('https');
const http = require('http');

// This method is called when your extension is activated
// Your extension is activated the very first time the command is executed
function activate(context) {

	// Use the console to output diagnostic information (console.log) and errors (console.error)
	// This line of code will only be executed once when your extension is activated
	console.log('Congratulations, your extension "nexus-ai-vscode-extension" is now active!');

	// Helper function to make HTTP requests to Nexus AI backend
	function makeNexusRequest(path, method = 'POST', data = null) {
		return new Promise((resolve, reject) => {
			const config = vscode.workspace.getConfiguration('nexusAI');
			const endpoint = config.get('apiEndpoint', 'http://localhost:8000');
			const apiKey = config.get('apiKey', '');
			
			const options = {
				method: method,
				headers: {
					'Content-Type': 'application/json',
					...(apiKey ? { 'Authorization': `Bearer ${apiKey}` } : {})
				}
			};
			
			const lib = endpoint.startsWith('https') ? https : http;
			const req = lib.request(`${endpoint}${path}`, options, (res) => {
				let data = '';
				res.on('data', chunk => data += chunk);
				res.on('end', () => {
					try {
						const parsed = JSON.parse(data);
						resolve(parsed);
					} catch (e) {
						reject(new Error(`Failed to parse response: ${e.message}`));
					}
				});
			});
			
			req.on('error', (e) => {
				reject(new Error(`Request failed: ${e.message}`));
			});
			
			if (data !== null) {
				req.write(JSON.stringify(data));
			}
			
			req.end();
		});
	}

	// The command has been defined in the package.json file
	// Now provide the implementation of the command with  registerCommand
	// The commandId parameter must match the command field in package.json
	const disposableChat = vscode.commands.registerCommand('nexusAI.chat', async () => {
		// The code you place here will be executed when your command is called
		const input = await vscode.window.showInputBox({
			prompt: 'Enter your message for Nexus AI',
			placeHolder: 'Ask me anything...'
		});
		
		if (!input) {
			return; // User cancelled
		}
		
		vscode.window.withProgress({
			location: vscode.ProgressLocation.Window,
			title: "Contacting Nexus AI...",
			cancellable: true
		}, async (progress, token) => {
			token.onCancellationRequested(() => {
				vscode.window.showInformationMessage('Request cancelled.');
			});
			
			try {
				const response = await makeNexusRequest('/v1/chat/completions', 'POST', {
					model: 'nexus-ai/auto',
					messages: [{ role: 'user', content: input }],
					stream: false
				});
				
				const message = response.choices?.[0]?.message?.content || 
							   response.result || 
							   'No response received from Nexus AI';
								
				vscode.window.showInformationMessage(`Nexus AI: ${message}`);
			} catch (error) {
				vscode.window.showErrorMessage(`Failed to contact Nexus AI: ${error.message}`);
			}
		});
	});

	const disposableImage = vscode.commands.registerCommand('nexusAI.generateImage', async () => {
		// The code you place here will be executed when your command is called
		const input = await vscode.window.showInputBox({
			prompt: 'Describe the image you want to generate',
			placeHolder: 'A beautiful sunset over mountains...'
		});
		
		if (!input) {
			return; // User cancelled
		}
		
		vscode.window.withProgress({
			location: vscode.ProgressLocation.Window,
			title: "Generating image...",
			cancellable: true
		}, async (progress, token) => {
			token.onCancellationRequested(() => {
				vscode.window.showInformationMessage('Image generation cancelled.');
			});
			
			try {
				const response = await makeNexusRequest('/v1/agent', 'POST', {
					task: `Generate an image of: ${input}`,
					stream: false
				});
				
				const imageResult = response.result || 
								   response.output || 
								   'Image generated successfully';
								   
				// Check if we got image data (base64)
				if (imageResult && imageResult.startsWith('data:image')) {
					// Show the image in a webview panel
					const panel = vscode.window.createWebviewPanel(
						'nexusAIImage',
						'Nexus AI Generated Image',
						vscode.ViewColumn.Beside,
						{
							enableScripts: true,
							localResourceRoots: []
						}
					);
					
					panel.webview.html = `<!DOCTYPE html>
					<html lang="en">
					<head>
						<meta charset="UTF-8">
						<meta name="viewport" content="width=device-width, initial-scale=1.0">
						<title>Nexus AI Generated Image</title>
						<style>
							body { margin: 0; padding: 20px; display: flex; justify-content: center; align-items: center; }
							img { max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
						</style>
					</head>
					<body>
						<img src="${imageResult}" alt="Generated image">
						<p style="margin-top: 15px; text-align: center; color: #666;">${input}</p>
					</body>
					</html>`;
				} else {
					vscode.window.showInformationMessage(`Nexus AI: ${imageResult}`);
				}
			} catch (error) {
				vscode.window.showErrorMessage(`Failed to generate image: ${error.message}`);
			}
		});
	});

	const disposableVoice = vscode.commands.registerCommand('nexusAI.voiceInput', async () => {
		// The code you place here will be executed when your command is called
		vscode.window.showInformationMessage('Voice input feature - Speaking not supported in this environment. Using text input instead.');
		
		const input = await vscode.window.showInputBox({
			prompt: 'What would you like to ask Nexus AI? (Voice input simulation)',
			placeHolder: 'Speak your command...'
		});
		
		if (!input) {
			return; // User cancelled
		}
		
		vscode.window.withProgress({
			location: vscode.ProgressLocation.Window,
			title: "Processing voice command...",
			cancellable: true
		}, async (progress, token) => {
			token.onCancellationRequested(() => {
				vscode.window.showInformationMessage('Request cancelled.');
			});
			
			try {
				const response = await makeNexusRequest('/v1/agent', 'POST', {
					task: input,
					stream: false
				});
				
				const message = response.result || 
							   response.output || 
							   'No response received from Nexus AI';
								
				vscode.window.showInformationMessage(`Nexus AI Response: ${message}`);
			} catch (error) {
				vscode.window.showErrorMessage(`Failed to process voice command: ${error.message}`);
			}
		});
	});

	// nostack: list available virtual team skills
	const disposableNostackList = vscode.commands.registerCommand('nexusAI.nostackList', async () => {
		try {
			const response = await makeNexusRequest('/nostack/skills', 'GET');
			const skills = response.skills || [];
			if (skills.length === 0) {
				vscode.window.showInformationMessage('No nostack skills available. Run "nostack/setup" to install.');
				return;
			}
			const items = skills.map(s => ({
				label: `$(rocket) ${s.name}`,
				description: s.command,
				detail: s.description,
				skill: s,
			}));
			const picked = await vscode.window.showQuickPick(items, {
				placeHolder: 'Select a nostack skill to run...',
				matchOnDescription: true,
				matchOnDetail: true,
			});
			if (picked) {
				const task = await vscode.window.showInputBox({
					prompt: `What should /${picked.skill.command.replace('/','')} work on?`,
					placeHolder: 'Describe the task...',
				});
				if (task) {
					vscode.commands.executeCommand('nexusAI.nostackRun', picked.skill.command.replace('/',''), task);
				}
			}
		} catch (error) {
			vscode.window.showErrorMessage(`Failed to list skills: ${error.message}`);
		}
	});

	// nostack: run a specific skill
	const disposableNostackRun = vscode.commands.registerCommand('nexusAI.nostackRun', async (skillName, task) => {
		if (!skillName) {
			skillName = await vscode.window.showInputBox({
				prompt: 'Enter nostack skill name',
				placeHolder: 'office-hours',
			});
			if (!skillName) return;
		}
		if (!task) {
			task = await vscode.window.showInputBox({
				prompt: `What should /${skillName} work on?`,
				placeHolder: 'Describe the task...',
			});
			if (!task) return;
		}
		vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: `Running /${skillName}...`,
			cancellable: true,
		}, async (progress, token) => {
			try {
				const response = await makeNexusRequest(`/nostack/skills/${skillName}/run`, 'POST', { task });
				const result = response.result || response.error || 'No result';
				const document = await vscode.workspace.openTextDocument({
					content: `# Nostack: /${skillName}\n\n## Task\n${task}\n\n## Result\n${result}`,
					language: 'markdown',
				});
				await vscode.window.showTextDocument(document, { preview: false });
				vscode.window.showInformationMessage(`/${skillName} completed`);
			} catch (error) {
				vscode.window.showErrorMessage(`Skill error: ${error.message}`);
			}
		});
	});

	// nostack: run a sprint (chain of skills)
	const disposableNostackSprint = vscode.commands.registerCommand('nexusAI.nostackSprint', async () => {
		const task = await vscode.window.showInputBox({
			prompt: 'Describe the overall task for the sprint',
			placeHolder: 'Build a REST API for user management',
		});
		if (!task) return;
		const skillsInput = await vscode.window.showInputBox({
			prompt: 'Enter skills to run (comma-separated)',
			placeHolder: 'office-hours, plan-ceo-review, review, ship',
			value: 'office-hours, plan-ceo-review, review, ship',
		});
		if (!skillsInput) return;
		const skills = skillsInput.split(',').map(s => s.trim()).filter(Boolean);
		vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: `Running sprint: ${skills.length} skills...`,
			cancellable: true,
		}, async (progress, token) => {
			try {
				const response = await makeNexusRequest('/nostack/sprint', 'POST', { task, skills });
				const lines = [`# Sprint: ${task}`, '', `Skills run: ${response.skills_run}`, ''];
				for (const r of (response.results || [])) {
					lines.push(`## /${r.skill}`, '', r.result || '(no output)', '');
				}
				const document = await vscode.workspace.openTextDocument({
					content: lines.join('\n'),
					language: 'markdown',
				});
				await vscode.window.showTextDocument(document, { preview: false });
				vscode.window.showInformationMessage(`Sprint completed: ${response.skills_run} skills run`);
			} catch (error) {
				vscode.window.showErrorMessage(`Sprint error: ${error.message}`);
			}
		});
	});

	context.subscriptions.push(
		disposableChat, disposableImage, disposableVoice,
		disposableNostackList, disposableNostackRun, disposableNostackSprint,
	);
}

// This method is called when your extension is deactivated
function deactivate() {}

module.exports = {
	activate,
	deactivate
}