let playerId = null;
let roomCode = null;
let isHost = false;
let gameState = null;
let selectedHandCard = null;
let currentPower = null;

const API_BASE = '/api';
const STORAGE_PREFIX = 'carrots_';

function saveSession() {
    localStorage.setItem(STORAGE_PREFIX + 'playerId', playerId);
    localStorage.setItem(STORAGE_PREFIX + 'roomCode', roomCode);
    localStorage.setItem(STORAGE_PREFIX + 'isHost', isHost);
}

function loadSession() {
    const savedPlayerId = localStorage.getItem(STORAGE_PREFIX + 'playerId');
    const savedRoomCode = localStorage.getItem(STORAGE_PREFIX + 'roomCode');
    const savedIsHost = localStorage.getItem(STORAGE_PREFIX + 'isHost');
    
    if (savedPlayerId && savedRoomCode) {
        return {
            playerId: parseInt(savedPlayerId),
            roomCode: savedRoomCode,
            isHost: savedIsHost === 'true'
        };
    }
    return null;
}

function clearSession() {
    localStorage.removeItem(STORAGE_PREFIX + 'playerId');
    localStorage.removeItem(STORAGE_PREFIX + 'roomCode');
    localStorage.removeItem(STORAGE_PREFIX + 'isHost');
}

async function tryReconnect() {
    const session = loadSession();
    if (!session) return false;
    
    try {
        const state = await apiCall(`/game-state/${session.roomCode}/?player_id=${session.playerId}`);
        
        playerId = session.playerId;
        roomCode = session.roomCode;
        isHost = session.isHost;
        gameState = state;
        
        if (state.state === 'waiting') {
            document.getElementById('room-code-display').textContent = roomCode;
            document.getElementById('start-btn').style.display = isHost ? 'block' : 'none';
            document.getElementById('waiting-msg').style.display = isHost ? 'none' : 'block';
            showScreen('waiting-screen');
            pollGameState();
        } else if (state.state === 'playing') {
            document.getElementById('game-room-code').textContent = roomCode;
            showScreen('game-screen');
            pollGameState();
        } else if (state.state === 'finished') {
            showGameOver();
        }
        
        return true;
    } catch (error) {
        clearSession();
        return false;
    }
}

async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' }
    };
    
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    const result = await response.json();
    
    if (!response.ok) {
        throw new Error(result.error || 'API error');
    }
    
    return result;
}

function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(screenId).classList.add('active');
}

async function createRoom() {
    const name = document.getElementById('player-name').value.trim();
    if (!name) {
        alert('Please enter your name');
        return;
    }
    
    try {
        const result = await apiCall('/create-room/', 'POST', { name });
        playerId = result.player_id;
        roomCode = result.room_code;
        isHost = true;
        
        saveSession();
        
        document.getElementById('room-code-display').textContent = roomCode;
        document.getElementById('start-btn').style.display = 'block';
        document.getElementById('waiting-msg').style.display = 'none';
        
        showScreen('waiting-screen');
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

async function joinRoom() {
    const name = document.getElementById('player-name').value.trim();
    const code = document.getElementById('room-code-input').value.trim().toUpperCase();
    
    if (!name || !code) {
        alert('Please enter your name and room code');
        return;
    }
    
    try {
        const result = await apiCall('/join-room/', 'POST', { name, room_code: code });
        playerId = result.player_id;
        roomCode = result.room_code;
        isHost = false;
        
        saveSession();
        
        document.getElementById('room-code-display').textContent = roomCode;
        document.getElementById('start-btn').style.display = 'none';
        document.getElementById('waiting-msg').style.display = 'block';
        
        showScreen('waiting-screen');
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

async function startGame() {
    try {
        await apiCall('/start-game/', 'POST', { player_id: playerId });
        showScreen('game-screen');
        document.getElementById('game-room-code').textContent = roomCode;
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

async function pollGameState() {
    if (!roomCode) return;
    
    try {
        const state = await apiCall(`/game-state/${roomCode}/?player_id=${playerId}`);
        gameState = state;
        updateUI();
        
        if (state.state === 'playing') {
            setTimeout(pollGameState, 2000);
        } else if (state.state === 'finished') {
            showGameOver();
        } else {
            setTimeout(pollGameState, 2000);
        }
    } catch (error) {
        console.error('Poll error:', error);
        setTimeout(pollGameState, 5000);
    }
}

function updateUI() {
    if (!gameState) return;
    
    if (gameState.state === 'waiting') {
        updateWaitingRoom();
    } else if (gameState.state === 'playing') {
        if (document.getElementById('waiting-screen').classList.contains('active')) {
            showScreen('game-screen');
            document.getElementById('game-room-code').textContent = roomCode;
        }
        updateGameBoard();
    }
}

function updateWaitingRoom() {
    const playersList = document.getElementById('players-list');
    playersList.innerHTML = gameState.players.map(p => `
        <div class="player-item">
            <div class="position">${p.position + 1}</div>
            <span>${p.name}${p.id == playerId ? ' (you)' : ''}</span>
        </div>
    `).join('');
}

function updateGameBoard() {
    const myPlayer = gameState.players.find(p => p.id == playerId);
    const isMyTurn = gameState.current_player_id == playerId;
    
    document.getElementById('deck-count').textContent = gameState.deck_count;
    
    const turnIndicator = document.getElementById('turn-indicator');
    if (isMyTurn) {
        turnIndicator.textContent = 'Your Turn!';
        turnIndicator.className = 'turn-indicator my-turn';
    } else {
        const currentPlayer = gameState.players.find(p => p.id == gameState.current_player_id);
        turnIndicator.textContent = `${currentPlayer?.name}'s Turn`;
        turnIndicator.className = 'turn-indicator';
    }
    
    const discardDisplay = document.getElementById('discard-card-display');
    if (gameState.discard_pile) {
        const card = gameState.discard_pile;
        discardDisplay.textContent = `${card.value} ${getSuitSymbol(card.suit)}`;
        discardDisplay.className = `card face-up ${card.suit}`;
    } else {
        discardDisplay.textContent = 'Empty';
        discardDisplay.className = 'card face-up';
    }
    
    updateOpponents();
    updateMyCarrots(myPlayer);
    updateMyHand(myPlayer);
    updateButtons(isMyTurn);
}

function updateOpponents() {
    const opponentsArea = document.getElementById('opponents-area');
    const opponents = gameState.players.filter(p => p.id != playerId);
    
    opponentsArea.innerHTML = opponents.map(p => `
        <div class="opponent" data-player-id="${p.id}">
            <h4>${p.name}</h4>
            <div class="carrots-grid">
                ${p.carrots.map((c, i) => `
                    <div class="card ${c.card ? `face-up ${c.card.suit}` : 'face-down'}" 
                         data-player-id="${p.id}" 
                         data-carrot-index="${i}"
                         onclick="handleOpponentCarrotClick(${p.id}, ${i})">
                        ${c.card ? `${c.card.value}${getSuitSymbol(c.card.suit)}` : ''}
                    </div>
                `).join('')}
            </div>
            <div style="margin-top: 10px; font-size: 0.8rem;">
                Cards: ${p.hand_count}
            </div>
        </div>
    `).join('');
}

function updateMyCarrots(myPlayer) {
    if (!myPlayer) return;
    
    const carrotsGrid = document.getElementById('my-carrots');
    carrotsGrid.innerHTML = myPlayer.carrots.map((c, i) => `
        <div class="card ${c.card ? `face-up ${c.card.suit}` : 'face-down'} ${selectedHandCard !== null ? 'selectable' : ''}"
             data-carrot-index="${i}"
             onclick="handleMyCarrotClick(${i})">
            ${c.card ? `${c.card.value}${getSuitSymbol(c.card.suit)}` : ''}
        </div>
    `).join('');
}

function updateMyHand(myPlayer) {
    if (!myPlayer) return;
    
    const handArea = document.getElementById('my-hand');
    const hand = myPlayer.hand || [];
    
    if (hand.length === 0) {
        handArea.innerHTML = `<div style="opacity: 0.7; padding: 20px;">No cards in hand</div>`;
        return;
    }
    
    handArea.innerHTML = hand.map((card, i) => `
        <div class="card face-up ${card.suit} ${selectedHandCard === i ? 'selected' : ''}"
             onclick="selectHandCard(${i})">
            ${card.value}${getSuitSymbol(card.suit)}
        </div>
    `).join('');
}

function selectHandCard(index) {
    selectedHandCard = selectedHandCard === index ? null : index;
    updateUI();
}

function updateButtons(isMyTurn) {
    const myPlayer = gameState?.players?.find(p => p.id == playerId);
    const hasHandCard = myPlayer && myPlayer.hand && myPlayer.hand.length > 0;
    
    const discardBtn = document.getElementById('discard-btn');
    const cookedBtn = document.getElementById('cooked-btn');
    
    discardBtn.disabled = !isMyTurn || !hasHandCard;
    cookedBtn.disabled = !isMyTurn;
}

function getSuitSymbol(suit) {
    const symbols = {
        hearts: '♥',
        diamonds: '♦',
        clubs: '♣',
        spades: '♠'
    };
    return symbols[suit] || '';
}

async function drawFromDeck() {
    if (!gameState || gameState.current_player_id != playerId) return;
    
    const myPlayer = gameState.players.find(p => p.id == playerId);
    if (myPlayer && myPlayer.hand && myPlayer.hand.length > 0) {
        alert('You already have a card in hand. Discard or replace it first.');
        return;
    }
    
    try {
        const result = await apiCall('/draw-card/', 'POST', { 
            player_id: playerId, 
            source: 'deck' 
        });
        
        await pollGameState();
        showDrawnCard(result.card, 'deck');
    } catch (error) {
        alert(error.message);
    }
}

async function drawFromDiscard() {
    if (!gameState || gameState.current_player_id != playerId) return;
    if (!gameState.discard_pile) return;
    
    const myPlayer = gameState.players.find(p => p.id == playerId);
    if (myPlayer && myPlayer.hand && myPlayer.hand.length > 0) {
        alert('You already have a card in hand. Discard or replace it first.');
        return;
    }
    
    try {
        const result = await apiCall('/draw-card/', 'POST', { 
            player_id: playerId, 
            source: 'discard' 
        });
        
        await pollGameState();
        showDrawnCard(result.card, 'discard');
    } catch (error) {
        alert(error.message);
    }
}

function showDrawnCard(card, source) {
    const modal = document.getElementById('power-modal');
    const title = document.getElementById('power-modal-title');
    const body = document.getElementById('power-modal-body');
    
    title.textContent = 'You drew:';
    body.innerHTML = `
        <div class="card face-up ${card.suit}" style="margin: 20px auto;">
            ${card.value}${getSuitSymbol(card.suit)}
        </div>
        <div class="action-buttons" style="justify-content: center; margin-top: 20px;">
            <button onclick="handleDiscardDrawnCard()" class="btn secondary">Discard</button>
            <button onclick="handleReplaceWithDrawnCard()" class="btn primary">Replace Carrot</button>
        </div>
    `;
    
    modal.style.display = 'flex';
    currentPower = { card, source };
}

async function handleDiscardDrawnCard() {
    const card = currentPower?.card;
    document.getElementById('power-modal').style.display = 'none';
    currentPower = null;
    
    try {
        await apiCall('/discard-card/', 'POST', { player_id: playerId });
        
        if (card?.value === '7') {
            showPowerSevenModal();
        } else if (card?.value === '8') {
            showPowerEightModal();
        } else if (card?.value === '9') {
            showPowerNineModal();
        } else {
            pollGameState();
        }
    } catch (error) {
        alert(error.message);
    }
}

function handleReplaceWithDrawnCard() {
    document.getElementById('power-modal').style.display = 'none';
    
    const myPlayer = gameState.players.find(p => p.id == playerId);
    if (myPlayer && myPlayer.hand && myPlayer.hand.length > 0) {
        selectedHandCard = myPlayer.hand.length - 1;
    }
    
    const carrotsGrid = document.getElementById('my-carrots');
    carrotsGrid.classList.add('select-mode');
}

async function handleMyCarrotClick(carrotIndex) {
    if (selectedHandCard === null) return;
    
    try {
        await apiCall('/replace-carrot/', 'POST', { 
            player_id: playerId,
            hand_card_index: selectedHandCard,
            carrot_index: carrotIndex
        });
        
        selectedHandCard = null;
        document.getElementById('my-carrots').classList.remove('select-mode');
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

function showPowerSevenModal() {
    const modal = document.getElementById('power-modal');
    const title = document.getElementById('power-modal-title');
    const body = document.getElementById('power-modal-body');
    
    const myPlayer = gameState.players.find(p => p.id == playerId);
    
    title.textContent = 'Power 7 - Peek';
    body.innerHTML = `
        <p>Select one of your carrots to look at:</p>
        <div style="display: flex; gap: 10px; justify-content: center; margin-top: 20px;">
            ${myPlayer.carrots.map((c, i) => `
                <div class="card face-down" 
                     onclick="usePowerSeven(${i})"
                     style="width: 60px; height: 84px; cursor: pointer;">
                    ${i + 1}
                </div>
            `).join('')}
        </div>
    `;
    
    modal.style.display = 'flex';
}

async function usePowerSeven(carrotIndex) {
    document.getElementById('power-modal').style.display = 'none';
    
    try {
        const result = await apiCall('/use-power/', 'POST', {
            player_id: playerId,
            power: '7',
            target_carrot_index: carrotIndex
        });
        
        const modal = document.getElementById('power-modal');
        const title = document.getElementById('power-modal-title');
        const body = document.getElementById('power-modal-body');
        
        title.textContent = 'Power 7 - Peek';
        body.innerHTML = `
            <p>Your carrot ${carrotIndex + 1} is:</p>
            <div class="card face-up ${result.carrot?.suit || ''}" style="margin: 20px auto;">
                ${result.carrot ? `${result.carrot.value}${getSuitSymbol(result.carrot.suit)}` : 'Empty'}
            </div>
        `;
        modal.style.display = 'flex';
        
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

async function discardCard() {
    if (!gameState || gameState.current_player_id != playerId) return;
    
    const myPlayer = gameState.players.find(p => p.id == playerId);
    if (!myPlayer || !myPlayer.hand || myPlayer.hand.length === 0) return;
    
    const discardIndex = selectedHandCard !== null ? selectedHandCard : 0;
    const card = myPlayer.hand[discardIndex];
    
    try {
        await apiCall('/discard-card/', 'POST', { player_id: playerId, hand_card_index: discardIndex });
        selectedHandCard = null;
        
        if (card.value === '7') {
            showPowerSevenModal();
        } else if (card.value === '8') {
            showPowerEightModal();
        } else if (card.value === '9') {
            showPowerNineModal();
        } else {
            pollGameState();
        }
    } catch (error) {
        alert(error.message);
    }
}

function showPowerEightModal() {
    const modal = document.getElementById('power-modal');
    const title = document.getElementById('power-modal-title');
    const body = document.getElementById('power-modal-body');
    
    const opponents = gameState.players.filter(p => p.id != playerId);
    
    title.textContent = 'Power 8 - Peek at Opponent';
    body.innerHTML = `
        <p>Select an opponent's carrot to look at:</p>
        <div id="power8-targets">
            ${opponents.map(p => `
                <div class="target-option">
                    <strong>${p.name}</strong>
                    <div style="display: flex; gap: 5px; margin-top: 10px;">
                        ${p.carrots.map((c, i) => `
                            <div class="card face-down" 
                                 onclick="usePowerEight(${p.id}, ${i})"
                                 style="width: 40px; height: 56px; font-size: 0.7rem;">
                                ${i + 1}
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('')}
        </div>
    `;
    
    modal.style.display = 'flex';
}

async function usePowerEight(targetPlayerId, carrotIndex) {
    document.getElementById('power-modal').style.display = 'none';
    
    try {
        const result = await apiCall('/use-power/', 'POST', {
            player_id: playerId,
            power: '8',
            target_player_id: targetPlayerId,
            target_carrot_index: carrotIndex
        });
        
        showPowerResult('Power 8', result.carrot);
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

function showPowerNineModal() {
    const modal = document.getElementById('power-modal');
    const title = document.getElementById('power-modal-title');
    const body = document.getElementById('power-modal-body');
    
    title.textContent = 'Power 9 - Swap';
    body.innerHTML = `
        <p>Select two carrots to swap:</p>
        <div id="swap-selections">
            <div id="swap1" class="target-option">First carrot: Not selected</div>
            <div id="swap2" class="target-option">Second carrot: Not selected</div>
        </div>
        <div id="all-carrots" style="margin-top: 20px;"></div>
    `;
    
    modal.style.display = 'flex';
    renderAllCarrotsForSwap();
}

let swapSelections = [];

function renderAllCarrotsForSwap() {
    const container = document.getElementById('all-carrots');
    container.innerHTML = gameState.players.map(p => `
        <div style="margin: 10px 0;">
            <strong>${p.name}</strong>
            <div style="display: flex; gap: 5px; margin-top: 5px;">
                ${p.carrots.map((c, i) => `
                    <div class="card face-down" 
                         onclick="selectSwapCarrot(${p.id}, ${i})"
                         style="width: 40px; height: 56px; font-size: 0.7rem;">
                        ${i + 1}
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function selectSwapCarrot(selPlayerId, carrotIndex) {
    swapSelections.push({ playerId: selPlayerId, carrotIndex });
    
    if (swapSelections.length === 1) {
        document.getElementById('swap1').textContent = `First carrot: Player ${selPlayerId}, Carrot ${carrotIndex + 1}`;
    } else if (swapSelections.length === 2) {
        document.getElementById('swap2').textContent = `Second carrot: Player ${selPlayerId}, Carrot ${carrotIndex + 1}`;
        executePowerNine();
    }
}

async function executePowerNine() {
    document.getElementById('power-modal').style.display = 'none';
    
    try {
        await apiCall('/use-power/', 'POST', {
            player_id: playerId,
            power: '9',
            carrot1_player_id: swapSelections[0].playerId,
            carrot1_index: swapSelections[0].carrotIndex,
            carrot2_player_id: swapSelections[1].playerId,
            carrot2_index: swapSelections[1].carrotIndex
        });
        
        swapSelections = [];
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

function showPowerResult(title, carrot) {
    const modal = document.getElementById('power-modal');
    const modalTitle = document.getElementById('power-modal-title');
    const body = document.getElementById('power-modal-body');
    
    modalTitle.textContent = title;
    body.innerHTML = `
        <p>Card revealed:</p>
        <div class="card face-up ${carrot?.suit || ''}" style="margin: 20px auto;">
            ${carrot ? `${carrot.value}${getSuitSymbol(carrot.suit)}` : 'Empty'}
        </div>
    `;
    
    modal.style.display = 'flex';
}

function handleOpponentCarrotClick(clickPlayerId, carrotIndex) {
    if (gameState?.discard_pile) {
        showMatchModal(clickPlayerId, carrotIndex);
    }
}

function showMatchModal(targetPlayerId, carrotIndex) {
    const modal = document.getElementById('match-modal');
    const targets = document.getElementById('match-targets');
    
    const targetPlayer = gameState.players.find(p => p.id == targetPlayerId);
    
    targets.innerHTML = `
        <p>Try to match ${targetPlayer.name}'s carrot ${carrotIndex + 1}?</p>
        <div class="action-buttons" style="justify-content: center; margin-top: 20px;">
            <button onclick="executeMatch(${targetPlayerId}, ${carrotIndex})" class="btn primary">Try Match</button>
            <button onclick="cancelMatch()" class="btn secondary">Cancel</button>
        </div>
    `;
    
    modal.style.display = 'flex';
}

async function executeMatch(targetPlayerId, carrotIndex) {
    document.getElementById('match-modal').style.display = 'none';
    
    try {
        const result = await apiCall('/try-match/', 'POST', {
            player_id: playerId,
            target_player_id: targetPlayerId,
            carrot_index: carrotIndex
        });
        
        if (result.matched) {
            alert('Match successful! Opponent loses a carrot.');
        } else {
            alert('No match! You get 2 penalty cards.');
        }
        
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

function cancelMatch() {
    document.getElementById('match-modal').style.display = 'none';
}

async function claimCooked() {
    if (!gameState || gameState.current_player_id != playerId) return;
    
    try {
        await apiCall('/claim-cooked/', 'POST', { player_id: playerId });
        alert('You claimed cooked! Final round begins.');
        pollGameState();
    } catch (error) {
        alert(error.message);
    }
}

function cancelPower() {
    document.getElementById('power-modal').style.display = 'none';
    currentPower = null;
}

async function showGameOver() {
    try {
        const result = await apiCall(`/scores/${roomCode}/`);
        
        const scoresList = document.getElementById('final-scores');
        scoresList.innerHTML = result.scores.map((s, i) => `
            <div class="score-item ${i === 0 ? 'winner' : ''}">
                <span>${i === 0 ? '🏆 ' : ''}${s.name}</span>
                <span>${s.score} points</span>
            </div>
        `).join('');
        
        showScreen('gameover-screen');
    } catch (error) {
        console.error('Error loading scores:', error);
    }
}

function backToLobby() {
    clearSession();
    playerId = null;
    roomCode = null;
    isHost = false;
    gameState = null;
    selectedHandCard = null;
    currentPower = null;
    
    showScreen('lobby-screen');
}

document.addEventListener('DOMContentLoaded', function() {
    tryReconnect();
});
