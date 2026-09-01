function getToken() {
    let token = localStorage.getItem('bmoToken');
    if (!token) {
        token = prompt("Enter BMO API token (see config.json 'api_token'):") || '';
        localStorage.setItem('bmoToken', token);
    }
    return token;
}

document.addEventListener('DOMContentLoaded', () => {

    // Status polling
    setInterval(pollStatus, 2000);
    pollStatus();
    
    // Setup listeners
    document.getElementById('send-cmd-btn').addEventListener('click', () => {
        const input = document.getElementById('command-input');
        if (input.value.trim()) {
            sendCommand(input.value.trim());
            input.value = '';
        }
    });
    
    document.getElementById('command-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('send-cmd-btn').click();
        }
    });
    
    document.getElementById('speak-btn').addEventListener('click', () => {
        const input = document.getElementById('speak-input');
        if (input.value.trim()) {
            sendSpeak(input.value.trim());
            input.value = '';
        }
    });
    
    document.getElementById('speak-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('speak-btn').click();
        }
    });
});

async function pollStatus() {
    try {
        const response = await fetch('/api/status');
        if (response.ok) {
            const data = await response.json();
            updateUIState(data.state, data.spotify_playing);
        }
    } catch (e) {
        updateUIState('error', false);
        console.error("Failed to fetch status:", e);
    }
}

function updateUIState(state, spotify) {
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    const face = document.querySelector('.face-container');
    const spTxt = document.getElementById('spotify-text');
    
    dot.className = 'dot ' + state;
    txt.textContent = state.toUpperCase();
    
    if (state === 'speak') {
        face.classList.add('speaking');
    } else {
        face.classList.remove('speaking');
    }
    
    if (spotify) {
        spTxt.textContent = "Music Playing";
        spTxt.parentElement.style.opacity = '1';
        spTxt.parentElement.style.color = '#fff';
    } else {
        spTxt.textContent = "Music Paused";
        spTxt.parentElement.style.opacity = '0.5';
        spTxt.parentElement.style.color = 'var(--bmo-text)';
    }
}

async function sendCommand(command) {
    // Optimistic UI update
    updateUIState('think', false);
    
    try {
        await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-BMO-Token': getToken() },
            body: JSON.stringify({ command: command })
        });
    } catch (e) {
        console.error("Failed to send command:", e);
    }
}

async function sendSpeak(text) {
    try {
        await fetch('/api/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-BMO-Token': getToken() },
            body: JSON.stringify({ text: text })
        });
    } catch (e) {
        console.error("Failed to send speak:", e);
    }
}
