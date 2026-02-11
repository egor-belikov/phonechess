/**
 * PhoneChess — этап 2: доска, часы, ходы, валидация.
 * Только смартфоны: планшеты и десктоп блокируются.
 */
(function () {
  console.log('[PhoneChess] script start');
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
  if (!MOBILE_ONLY_ENABLED) {
    var block = document.getElementById('mobile-only-block');
    if (block) block.style.display = 'none';
  }

  const TIME_CONTROLS = ['3+0', '3+2', '5+0', '5+3', '10+0', '15+10'];
  const FILES = 'abcdefgh';
  /** Один спрайт: Chess_Pieces_Sprite.svg (270×90), порядок K,Q,B,N,R,P; ряд 0=белые, 1=чёрные */
  const PIECE_SPRITE_URL = '/pieces/Chess_Pieces_Sprite.svg';
  const SPRITE_COL = { K: 0, Q: 1, B: 2, N: 3, R: 4, P: 5 };
  function pieceSpriteOffset(fenLetter) {
    if (!fenLetter) return { col: 0, row: 0 };
    const row = fenLetter === fenLetter.toUpperCase() ? 0 : 1;
    const col = SPRITE_COL[fenLetter.toUpperCase()] ?? 0;
    return { col: col, row: row };
  }

  const API_URL = (function () {
    const base = document.baseURI || window.location.href;
    if (!base || base === 'about:blank' || base.startsWith('file:')) {
      console.warn('[PhoneChess] No valid page URL, using location.host');
    }
    const u = new URL(base || ('https://' + window.location.host));
    const protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return protocol + '//' + u.host;
  })();
  console.log('[PhoneChess] API_URL', API_URL);

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
  let boardFlipped = false;
  let lastClockTick = 0;
  let resignConfirming = false;
  let resignConfirmTimeout = null;
  let draggedSquare = null;

  const $ = (id) => document.getElementById(id);
  const lobbyButtons = $('lobby-buttons');
  const lobbyScreen = $('lobby-screen');
  const gameScreen = $('game-screen');
  const wsStatus = $('ws-status');
  const btnBackGame = $('btn-back-game');
  const gameInfo = $('game-info');
  const clockTop = $('clock-top');
  const clockBottom = $('clock-bottom');
  const clockTopLabel = $('clock-top-label');
  const clockBottomLabel = $('clock-bottom-label');
  const gameYourSideEl = $('game-your-side');
  const boardEl = $('chess-board');
  const moveListEl = $('move-list');
  const btnResign = $('btn-resign');
  const btnFlipBoard = $('btn-flip-board');

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
      const isYou = key === currentQueue;
      const countText = isYou ? n + ' в очереди (и вы)' : n + ' в очереди';
      const cls = isYou ? 'mode-btn in-queue' : 'mode-btn';
      return `<button type="button" class="${cls}" data-time="${key}"><span>${key}</span><span class="queue-count">${countText}</span></button>`;
    }).join('');
    lobbyButtons.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => onModeClick(btn.dataset.time));
    });
  }

  function onModeClick(timeControl) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (timeControl === currentQueue) {
      ws.send(JSON.stringify({ type: 'leave_queue', time_control: timeControl }));
      currentQueue = null;
      return;
    }
    if (currentQueue) {
      ws.send(JSON.stringify({ type: 'leave_queue', time_control: currentQueue }));
      currentQueue = null;
    }
    currentQueue = timeControl;
    ws.send(JSON.stringify({ type: 'join_queue', time_control: timeControl }));
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
    if (clockTopLabel) clockTopLabel.textContent = isWhite ? 'Соперник (чёрные)' : 'Соперник (белые)';
    if (clockBottomLabel) clockBottomLabel.textContent = isWhite ? 'Вы (белые)' : 'Вы (чёрные)';
    if (gameYourSideEl) gameYourSideEl.textContent = isWhite ? 'Вы играете белыми' : 'Вы играете чёрными';
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
    if (lastClockTick > 0 && isOurTurn) {
      const elapsed = Math.min(now - lastClockTick, 1000);
      if (turn === 'white') whiteRemainingMs = Math.max(0, whiteRemainingMs - elapsed);
      else blackRemainingMs = Math.max(0, blackRemainingMs - elapsed);
    }
    lastClockTick = now;
    updateClocksDisplay();
  }

  function startClockTicker() {
    if (clockInterval) clearInterval(clockInterval);
    lastClockTick = Date.now();
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
    if (!boardEl || !gameFen) {
      console.log('[PhoneChess] renderBoard skip', { boardEl: !!boardEl, gameFen: !!gameFen });
      return;
    }
    if (typeof window.Chess === 'undefined') {
      console.error('[PhoneChess] Chess (chess.js) not loaded');
      return;
    }
    try {
    const orientation = myColor === 'black' ? 'black' : 'white';
    const effectiveOrientation = boardFlipped ? (orientation === 'white' ? 'black' : 'white') : orientation;
    const board = parseFenPieces(gameFen);
    boardEl.innerHTML = '';
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const br = getDisplayRankRow(row, effectiveOrientation);
        const piece = board[br] && board[br][col];
        const isLight = (row + col) % 2 === 0;
        const sq = FILES[col] + (8 - br);
        const div = document.createElement('div');
        div.className = 'square ' + (isLight ? 'light' : 'dark');
        div.dataset.square = sq;
        if (piece) {
          const off = pieceSpriteOffset(piece);
          const wrap = document.createElement('div');
          wrap.className = 'piece-sprite';
          wrap.style.backgroundImage = 'url(' + PIECE_SPRITE_URL + ')';
          wrap.style.backgroundSize = '600% 200%';
          // background-position %: (container - image) * p = offset. 6 cols → p = col/5; 2 rows → p = row/1
          wrap.style.backgroundPosition = (off.col * 20) + '% ' + (off.row * 100) + '%';
          wrap.setAttribute('aria-label', piece);
          div.appendChild(wrap);
        }
    var isOurPiece = piece && (myColor === 'white' ? /[KQRBNP]/.test(piece) : /[kqrbnp]/.test(piece));
    if (isOurPiece) {
      div.draggable = true;
      div.addEventListener('dragstart', function (e) {
        draggedSquare = sq;
        e.dataTransfer.setData('text/plain', sq);
        e.dataTransfer.effectAllowed = 'move';
      });
    }
        div.addEventListener('dragover', function (e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; });
        div.addEventListener('drop', function (e) {
          e.preventDefault();
          if (draggedSquare && draggedSquare !== sq) doMoveFromTo(draggedSquare, sq);
          draggedSquare = null;
        });
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
      const sq = cell.dataset.square;
      if (!sq) return;
      const handler = function () { onSquareClick(sq); };
      cell.addEventListener('click', handler);
      cell.addEventListener('touchend', function (e) { e.preventDefault(); handler(); }, { passive: false });
    });
    } catch (e) {
      console.error('[PhoneChess] renderBoard error', e);
    }
  }

  function doMoveFromTo(fromSq, toSq) {
    if (!currentGameId || !gameFen || gameResult) return;
    try {
      var c = new Chess(gameFen);
    } catch (e) { return; }
    var turn = c.turn();
    var ourTurn = (turn === 'w' && myColor === 'white') || (turn === 'b' && myColor === 'black');
    if (!ourTurn) return;
    var moves = c.moves({ square: fromSq, verbose: true });
    var move = moves && moves.find(function (m) { return m.to === toSq; });
    if (!move) return;
    var promotion = (move.flags || '').indexOf('p') !== -1 ? 'q' : null;
    ws.send(JSON.stringify({ type: 'make_move', game_id: currentGameId, from: fromSq, to: toSq, promotion: promotion }));
    selectedSquare = null;
    legalTargets = [];
    renderBoard();
  }

  function onSquareClick(sq) {
    if (!currentGameId || !gameFen || gameResult) {
      console.log('[PhoneChess] onSquareClick early return: no game/fen/result');
      return;
    }
    try {
      var c = new Chess(gameFen);
    } catch (e) {
      console.error('[PhoneChess] onSquareClick Chess error', e);
      return;
    }
    var turn = c.turn();
    var isWhite = turn === 'w';
    var ourTurn = (isWhite && myColor === 'white') || (!isWhite && myColor === 'black');
    if (!ourTurn) return;
    var piece = c.get(sq);
    var pieceColor = piece && typeof piece === 'object' ? piece.color : null;
    if (selectedSquare) {
      if (legalTargets.indexOf(sq) !== -1) {
        var from = selectedSquare;
        var promotion = null;
        var moves = c.moves({ square: from, verbose: true });
        var move = moves && moves.find(function (m) { return m.to === sq; });
        if (move && (move.flags || '').indexOf('p') !== -1) promotion = 'q';
        ws.send(JSON.stringify({ type: 'make_move', game_id: currentGameId, from: from, to: sq, promotion: promotion }));
        selectedSquare = null;
        legalTargets = [];
        renderBoard();
        return;
      }
      selectedSquare = null;
      legalTargets = [];
    } else if (pieceColor && ((isWhite && pieceColor === 'w') || (!isWhite && pieceColor === 'b'))) {
      selectedSquare = sq;
      var movesFrom = c.moves({ square: sq, verbose: true });
      legalTargets = movesFrom ? movesFrom.map(function (m) { return m.to; }) : [];
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
    console.log('[PhoneChess] applyGameState', { hasFen: !!data.fen, moves: data.moves?.length, result: data.result });
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
    console.log('[PhoneChess] enterGame', { game_id: msg.game_id, color: msg.color, hasFen: !!msg.fen });
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
    boardFlipped = false;
    if (resignConfirmTimeout) clearTimeout(resignConfirmTimeout);
    resignConfirming = false;
    if (btnResign) { btnResign.textContent = 'Сдаться'; btnResign.classList.remove('resign-confirm'); }
    if (gameInfo) gameInfo.textContent = (msg.white_username || 'Белые') + ' vs ' + (msg.black_username || 'Чёрные') + ' (' + (msg.time_control || '') + ')';
    showScreen('game-screen');
    updateClocksDisplay();
    startClockTicker();
    renderBoard();
    renderMoveList();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe_game', game_id: currentGameId }));
    }
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    var wsUrl = API_URL + '/ws';
    console.log('[PhoneChess] connect', wsUrl);
    setWsStatus('Подключение к серверу…');
    ws = new WebSocket(wsUrl);

    ws.onopen = function () {
      console.log('[PhoneChess] WS onopen');
      try {
        var initData = getInitData ? getInitData() : '';
        var payload = { type: 'auth', init_data: initData || '' };
        var debugUid = getDebugUid ? getDebugUid() : null;
        if (debugUid != null) payload.debug_uid = debugUid;
        ws.send(JSON.stringify(payload));
      } catch (e) {
        ws.send(JSON.stringify({ type: 'auth', init_data: '', debug_uid: 0 }));
      }
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
          console.log('[PhoneChess] WS game_state received');
          applyGameState(msg);
        } else if (msg.type === 'game_update') {
          applyGameState(msg);
        }
      } catch (e) {
        console.warn('ws message parse', e);
      }
    };

    ws.onclose = function (ev) {
      console.log('[PhoneChess] WS onclose', ev.code, ev.reason || '');
      ws = null;
      var closeMsg = 'Отключено: код ' + ev.code + (ev.reason ? ' — ' + ev.reason : '');
      setWsStatus(closeMsg, 'error');
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

    ws.onerror = function (e) {
      console.warn('[PhoneChess] WS onerror', e);
      setWsStatus('Ошибка соединения (WebSocket)', 'error');
    };
  }

  btnBackGame.addEventListener('click', function () {
    if (clockInterval) clearInterval(clockInterval);
    clockInterval = null;
    currentGameId = null;
    showScreen('lobby-screen');
  });
  if (btnFlipBoard) {
    btnFlipBoard.addEventListener('click', function () {
      boardFlipped = !boardFlipped;
      renderBoard();
    });
  }
  if (btnResign) {
    btnResign.addEventListener('click', function () {
      if (!currentGameId || gameResult) return;
      if (resignConfirming) {
        if (resignConfirmTimeout) clearTimeout(resignConfirmTimeout);
        resignConfirming = false;
        btnResign.textContent = 'Сдаться';
        btnResign.classList.remove('resign-confirm');
        ws.send(JSON.stringify({ type: 'resign', game_id: currentGameId }));
      } else {
        resignConfirming = true;
        btnResign.textContent = 'Точно сдаться?';
        btnResign.classList.add('resign-confirm');
        resignConfirmTimeout = setTimeout(function () {
          resignConfirming = false;
          btnResign.textContent = 'Сдаться';
          btnResign.classList.remove('resign-confirm');
          resignConfirmTimeout = null;
        }, 3000);
      }
    });
  }

  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }

  renderLobbyButtons({});
  connect();
})();
