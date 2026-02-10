/**
 * PhoneChess — этап 2: доска, часы, ходы, валидация.
 * Только смартфоны: планшеты и десктоп блокируются.
 */
(function () {
  /** Включить ограничение «только смартфон» (планшеты/десктоп блокируются). Пока false — для тестов с ноута. */
  const MOBILE_ONLY_ENABLED = false;

  /** Проверка «только телефон»: в Telegram — только android/ios, плюс ширина как у телефона (не планшет). */
  function isMobileOnly() {
    const tg = window.Telegram && window.Telegram.WebApp;
    if (tg && tg.platform) {
      if (tg.platform !== 'android' && tg.platform !== 'ios') return false;
    }
    const w = window.innerWidth || document.documentElement.clientWidth;
    return w <= 520;
  }

  function showMobileOnlyBlock() {
    const block = document.getElementById('mobile-only-block');
    if (block) block.classList.add('active');
    document.body.classList.add('mobile-blocked');
  }

  if (MOBILE_ONLY_ENABLED && !isMobileOnly()) {
    showMobileOnlyBlock();
    return;
  }

  const TIME_CONTROLS = ['3+0', '3+2', '5+0', '5+3', '10+0', '15+10'];
  const FILES = 'abcdefgh';
  const PIECES = { K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙', k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟' };

  const API_URL = (function () {
    const u = new URL(document.baseURI || window.location.href);
    const protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return protocol + '//' + u.host;
  })();

  let ws = null;
  let currentQueue = null;
  let reconnectTimer = null;
  let currentGameId = null;
  let myColor = null;
  let gameFen = null;
  let gameMoves = [];
  let whiteRemainingMs = 0;
  let blackRemainingMs = 0;
  let gameResult = null;
  let selectedSquare = null;
  let legalTargets = [];
  let lastMove = null;
  let clockInterval = null;

  const $ = (id) => document.getElementById(id);
  const lobbyButtons = $('lobby-buttons');
  const lobbyScreen = $('lobby-screen');
  const gameScreen = $('game-screen');
  const waitingScreen = $('waiting-screen');
  const wsStatus = $('ws-status');
  const btnCancelQueue = $('btn-cancel-queue');
  const btnBackGame = $('btn-back-game');
  const gameInfo = $('game-info');
  const clockTop = $('clock-top');
  const clockBottom = $('clock-bottom');
  const boardEl = $('chess-board');
  const moveListEl = $('move-list');

  function getInitData() {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
      return window.Telegram.WebApp.initData;
    }
    return '';
  }

  function getDebugUid() {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) return undefined;
    return Math.floor(Math.random() * 1e9);
  }

  function showScreen(id) {
    document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
    const el = document.getElementById(id);
    if (el) el.classList.add('active');
  }

  function setWsStatus(text, className) {
    wsStatus.textContent = text;
    wsStatus.className = 'ws-status' + (className ? ' ' + className : '');
  }

  function renderLobbyButtons(counts) {
    counts = counts || {};
    lobbyButtons.innerHTML = TIME_CONTROLS.map(key => {
      const n = counts[key] != null ? counts[key] : 0;
      return `<button type="button" class="mode-btn" data-time="${key}"><span>${key}</span><span class="queue-count">${n} в очереди</span></button>`;
    }).join('');
    lobbyButtons.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => onModeClick(btn.dataset.time));
    });
  }

  function onModeClick(timeControl) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    currentQueue = timeControl;
    ws.send(JSON.stringify({ type: 'join_queue', time_control: timeControl }));
    showScreen('waiting-screen');
  }

  function leaveCurrentQueue() {
    if (!currentQueue || !ws || ws.readyState !== WebSocket.OPEN) {
      showScreen('lobby-screen');
      currentQueue = null;
      return;
    }
    ws.send(JSON.stringify({ type: 'leave_queue', time_control: currentQueue }));
    currentQueue = null;
    showScreen('lobby-screen');
  }

  function formatClock(ms) {
    if (ms <= 0) return '0:00';
    const s = Math.ceil(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    if (ms < 20000) return m + ':' + (sec < 10 ? '0' : '') + sec + '.' + Math.floor((ms % 1000) / 100);
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }

  function updateClocksDisplay() {
    const isWhite = myColor === 'white';
    const topMs = isWhite ? blackRemainingMs : whiteRemainingMs;
    const bottomMs = isWhite ? whiteRemainingMs : blackRemainingMs;
    const ourTurn = (gameFen && gameFen.includes(' w ') && isWhite) || (gameFen && gameFen.includes(' b ') && !isWhite);
    if (clockTop) {
      clockTop.textContent = formatClock(topMs);
      clockTop.classList.toggle('low-time', topMs < 20000 && topMs > 0);
      clockTop.classList.remove('our-turn');
    }
    if (clockBottom) {
      clockBottom.textContent = formatClock(bottomMs);
      clockBottom.classList.toggle('low-time', bottomMs < 20000 && bottomMs > 0);
      clockBottom.classList.toggle('our-turn', ourTurn && !gameResult);
    }
  }

  function tickClocks() {
    if (gameResult) return;
    const now = Date.now();
    const fen = gameFen;
    if (!fen) return;
    const turn = fen.includes(' w ') ? 'white' : 'black';
    const isOurTurn = (turn === 'white' && myColor === 'white') || (turn === 'black' && myColor === 'black');
    if (!isOurTurn) {
      updateClocksDisplay();
      return;
    }
    const elapsed = (now % 1000) < 200 ? 100 : 0;
    if (turn === 'white') whiteRemainingMs = Math.max(0, whiteRemainingMs - elapsed);
    else blackRemainingMs = Math.max(0, blackRemainingMs - elapsed);
    updateClocksDisplay();
  }

  function startClockTicker() {
    if (clockInterval) clearInterval(clockInterval);
    clockInterval = setInterval(tickClocks, 100);
  }

  function parseFenPieces(fen) {
    const parts = fen.split(' ');
    const rows = parts[0].split('/');
    const board = [];
    for (let r = 0; r < 8; r++) {
      const line = rows[r] || '';
      let col = 0;
      const rowPieces = [];
      for (let i = 0; i < line.length && col < 8; i++) {
        const c = line[i];
        if (/\d/.test(c)) {
          const n = parseInt(c, 10);
          for (let k = 0; k < n; k++) rowPieces[col++] = null;
        } else {
          rowPieces[col++] = c;
        }
      }
      board.push(rowPieces);
    }
    return board;
  }

  function getDisplayRankRow(displayRow, orientation) {
    return orientation === 'black' ? displayRow : 7 - displayRow;
  }

  function renderBoard() {
    if (!boardEl || !gameFen) return;
    const orientation = myColor === 'black' ? 'black' : 'white';
    const board = parseFenPieces(gameFen);
    boardEl.innerHTML = '';
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const br = getDisplayRankRow(row, orientation);
        const piece = board[br] && board[br][col];
        const isLight = (row + col) % 2 === 0;
        const sq = FILES[col] + (8 - br);
        const div = document.createElement('div');
        div.className = 'square ' + (isLight ? 'light' : 'dark');
        div.dataset.square = sq;
        if (piece) div.textContent = PIECES[piece] || '';
        if (lastMove && (lastMove.from === sq || lastMove.to === sq)) div.classList.add('last-move');
        if (selectedSquare === sq) div.classList.add('selected');
        if (legalTargets.indexOf(sq) !== -1) div.classList.add('legal');
        if (window.Chess && (piece === 'K' || piece === 'k')) {
          try {
            const c = new Chess(gameFen);
            const turn = gameFen.includes(' w ') ? 'w' : 'b';
            if (c.in_check() && ((piece === 'K' && turn === 'w') || (piece === 'k' && turn === 'b'))) {
              div.classList.add('check');
            }
          } catch (e) {}
        }
        boardEl.appendChild(div);
      }
    }
    boardEl.querySelectorAll('.square').forEach(cell => {
      cell.addEventListener('click', () => onSquareClick(cell.dataset.square));
    });
  }

  function onSquareClick(sq) {
    if (!currentGameId || !gameFen || gameResult) return;
    const c = new Chess(gameFen);
    const turn = c.turn();
    const isWhite = turn === 'w';
    const ourTurn = (isWhite && myColor === 'white') || (!isWhite && myColor === 'black');
    if (!ourTurn) return;
    const piece = c.get(sq);
    if (selectedSquare) {
      if (legalTargets.indexOf(sq) !== -1) {
        const from = selectedSquare;
        let promotion = null;
        const moves = c.moves({ square: from, verbose: true });
        const move = moves.find(m => m.to === sq);
        if (move && move.flags.indexOf('p') !== -1) promotion = 'q';
        ws.send(JSON.stringify({ type: 'make_move', game_id: currentGameId, from: from, to: sq, promotion: promotion }));
        selectedSquare = null;
        legalTargets = [];
        return;
      }
      selectedSquare = null;
      legalTargets = [];
    } else if (piece && ((isWhite && piece.color === 'w') || (!isWhite && piece.color === 'b'))) {
      selectedSquare = sq;
      legalTargets = c.moves({ square: sq, verbose: true }).map(m => m.to);
    }
    renderBoard();
  }

  function renderMoveList() {
    if (!moveListEl) return;
    let html = '';
    let num = 1;
    for (let i = 0; i < gameMoves.length; i++) {
      const m = gameMoves[i];
      const t = Math.floor(m.time_ms / 1000);
      const min = Math.floor(t / 60);
      const sec = t % 60;
      const timeStr = min + ':' + (sec < 10 ? '0' : '') + sec;
      if (i % 2 === 0) html += '<span class="move-num">' + num++ + '.</span> ';
      html += m.san + ' <span class="move-time">(' + timeStr + ')</span> ';
    }
    moveListEl.innerHTML = html || '—';
  }

  function applyGameState(data) {
    gameFen = data.fen || gameFen;
    whiteRemainingMs = data.white_remaining_ms != null ? data.white_remaining_ms : whiteRemainingMs;
    blackRemainingMs = data.black_remaining_ms != null ? data.black_remaining_ms : blackRemainingMs;
    if (data.moves) gameMoves = data.moves;
    if (data.result !== undefined) gameResult = data.result;
    if (data.san && data.move_time_ms !== undefined) {
      gameMoves = gameMoves.concat([{ san: data.san, time_ms: data.move_time_ms }]);
    }
    if (data.from && data.to) lastMove = { from: data.from, to: data.to };
    updateClocksDisplay();
    startClockTicker();
    renderBoard();
    renderMoveList();
    if (gameResult && gameInfo) {
      const r = gameResult === '1-0' ? 'Белые выиграли' : gameResult === '0-1' ? 'Чёрные выиграли' : 'Ничья';
      gameInfo.textContent = gameInfo.textContent + ' — ' + r;
    }
  }

  function enterGame(msg) {
    currentGameId = msg.game_id;
    myColor = msg.color;
    gameFen = msg.fen;
    whiteRemainingMs = msg.white_remaining_ms != null ? msg.white_remaining_ms : 0;
    blackRemainingMs = msg.black_remaining_ms != null ? msg.black_remaining_ms : 0;
    gameMoves = [];
    gameResult = null;
    selectedSquare = null;
    legalTargets = [];
    lastMove = null;
    if (gameInfo) gameInfo.textContent = (msg.white_username || 'Белые') + ' vs ' + (msg.black_username || 'Чёрные') + ' (' + (msg.time_control || '') + ')';
    showScreen('game-screen');
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe_game', game_id: currentGameId }));
    }
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    setWsStatus('Подключение…');
    ws = new WebSocket(API_URL + '/ws');

    ws.onopen = function () {
      const initData = getInitData();
      const payload = { type: 'auth', init_data: initData };
      const debugUid = getDebugUid();
      if (debugUid != null) payload.debug_uid = debugUid;
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'queue_counts') {
          renderLobbyButtons(msg.counts);
          setWsStatus('Подключено', 'connected');
        } else if (msg.type === 'matched') {
          currentQueue = null;
          enterGame(msg);
        } else if (msg.type === 'game_state') {
          applyGameState(msg);
        } else if (msg.type === 'game_update') {
          applyGameState(msg);
        }
      } catch (e) {
        console.warn('ws message parse', e);
      }
    };

    ws.onclose = function () {
      ws = null;
      setWsStatus('Нет соединения', 'error');
      if (!reconnectTimer) {
        reconnectTimer = setInterval(function () {
          connect();
          if (ws && ws.readyState === WebSocket.OPEN) {
            clearInterval(reconnectTimer);
            reconnectTimer = null;
          }
        }, 3000);
      }
    };

    ws.onerror = function () {
      setWsStatus('Ошибка соединения', 'error');
    };
  }

  btnCancelQueue.addEventListener('click', leaveCurrentQueue);
  btnBackGame.addEventListener('click', function () {
    if (clockInterval) clearInterval(clockInterval);
    clockInterval = null;
    currentGameId = null;
    showScreen('lobby-screen');
  });

  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }

  renderLobbyButtons({});
  connect();
})();
