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
  const SUPPORTED_LANGS = [
    'en', 'ru', 'hi', 'id', 'pt', 'es', 'ar', 'fa', 'uz', 'uk',
    'fr', 'vi', 'tr', 'it', 'de', 'ms', 'bn', 'kk', 'zh', 'th',
    'pl', 'ko', 'ja', 'ur', 'ta', 'tl', 'nl', 'ro', 'az', 'am'
  ];
  const FILES = 'abcdefgh';
  const PREMOVE_COLORS = ['#4f8cff', '#ff9f43', '#22c55e', '#e879f9', '#f43f5e', '#14b8a6'];
  const STATE_RESYNC_MS = 1000;
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
  let legalTargetsMode = 'none'; // none | tap | drag
  let lastMove = null;
  let clockInterval = null;
  let boardFlipped = false;
  let lastClockTick = 0;
  let resignConfirming = false;
  let resignConfirmTimeout = null;
  let draggedSquare = null;
  let premoveQueue = [];
  let lastTouchTapAt = 0;
  let lastTouchTapSquare = null;
  let touchDragFromSquare = null;
  let touchDragTargetSquare = null;
  let touchDragMoved = false;
  let pendingPromotionChoice = null;
  let resultReason = null;
  let resultDetail = null;
  let isBotGame = false;
  let noClockUserId = null;
  let rematchAvailableGameId = null;
  let drawOfferBy = null;
  let drawOfferColor = null;
  let drawOfferPly = null;
  let opponentDisconnected = false;
  let opponentDisconnectGraceSeconds = 0;
  let opponentDisconnectedVisible = false;
  let opponentDisconnectDebounceTimer = null;
  let lastStateSyncAt = 0;
  let currentLang = 'ru';
  let i18nMessages = {};
  let pendingStartInviteKey = null;
  let replayMode = false;
  let replayFens = [];
  let replayMoves = [];
  let replayIndex = -1;
  let stockfishWorker = null;
  let analysisEnabled = false;
  let analysisRequestId = 0;
  let analysisDebounceTimer = null;
  let privateWaitingState = null;
  let pingMs = null;
  let pingInterval = null;
  let myTelegramId = 0;
  let profileData = null;
  let lastTournamentWaiting = { swiss: {}, ko: {} };

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
  const btnDraw = $('btn-draw');
  const btnClaimDraw = $('btn-claim-draw');
  const buildInfoEl = $('build-info');
  const materialCapturedTopEl = $('material-captured-top');
  const materialCapturedBottomEl = $('material-captured-bottom');
  const materialBalanceCenterEl = $('material-balance-center');
  const btnPrivateGame = $('btn-private-game');
  const btnBotGame = $('btn-bot-game');
  const btnProfile = $('btn-profile');
  const btnLogin = $('btn-login');
  const profileModalEl = $('profile-modal');
  const profileTitleEl = $('profile-title');
  const profileSummaryEl = $('profile-summary');
  const profileHistoryEl = $('profile-history');
  const profileTournamentsEl = $('profile-tournaments');
  const tournamentTcSelectEl = $('tournament-tc-select');
  const tourSwissCountEl = $('tour-swiss-count');
  const tourKoCountEl = $('tour-ko-count');
  const btnTourSwissJoin = $('btn-tour-swiss-join');
  const btnTourSwissLeave = $('btn-tour-swiss-leave');
  const btnTourKoJoin = $('btn-tour-ko-join');
  const btnTourKoLeave = $('btn-tour-ko-leave');
  const loginFormWrapEl = $('login-form-wrap');
  const loginInputEl = $('login-input');
  const btnLoginSubmit = $('btn-login-submit');
  const btnProfileClose = $('btn-profile-close');
  const privateWaitingPanelEl = $('private-waiting-panel');
  const privateWaitingTitleEl = $('private-waiting-title');
  const privateWaitingTextEl = $('private-waiting-text');
  const privateTimeModalEl = $('private-time-modal');
  const privateTimeGridEl = $('private-time-grid');
  const btnPrivateTimeClose = $('btn-private-time-close');
  const promotionPickerEl = $('promotion-picker');
  const promotionChoicesEl = $('promotion-choices');
  const gameAlertEl = $('game-alert');
  const resultModalEl = $('result-modal');
  const resultModalTitleEl = $('result-modal-title');
  const resultModalTextEl = $('result-modal-text');
  const btnResultLobby = $('btn-result-lobby');
  const btnResultRematch = $('btn-result-rematch');
  const btnResultAnalysis = $('btn-result-analysis');
  const btnReplayFirst = $('btn-replay-first');
  const btnReplayPrev = $('btn-replay-prev');
  const btnReplayNext = $('btn-replay-next');
  const btnReplayLast = $('btn-replay-last');
  const analysisPanelEl = $('analysis-panel');
  const analysisScoreEl = $('analysis-score');
  const analysisLineEl = $('analysis-line');
  const btnAnalysisToggle = $('btn-analysis-toggle');
  const pingIndicatorEl = $('ping-indicator');

  function deepGet(obj, path) {
    const parts = path.split('.');
    let cur = obj;
    for (let i = 0; i < parts.length; i++) {
      if (!cur || typeof cur !== 'object') return null;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function t(key, vars) {
    let value = deepGet(i18nMessages, key);
    if (typeof value !== 'string') value = key;
    if (!vars) return value;
    return value.replace(/\{(\w+)\}/g, function (_, name) {
      return vars[name] != null ? String(vars[name]) : '';
    });
  }

  function detectPreferredLang() {
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      const tgLang = tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code;
      if (tgLang) return tgLang;
    } catch (e) {}
    if (navigator.languages && navigator.languages.length) return navigator.languages[0];
    return navigator.language || 'ru';
  }

  function getStartParam() {
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      const p = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
      if (typeof p === 'string' && p) return p;
    } catch (e) {}
    try {
      const u = new URL(window.location.href);
      const direct =
        u.searchParams.get('tgWebAppStartParam') ||
        u.searchParams.get('startapp') ||
        u.searchParams.get('start_param') ||
        u.searchParams.get('start');
      if (direct) return direct;
      const hash = new URLSearchParams((u.hash || '').replace(/^#/, ''));
      const fromHash =
        hash.get('tgWebAppStartParam') ||
        hash.get('startapp') ||
        hash.get('start_param') ||
        hash.get('start');
      if (fromHash) return fromHash;
    } catch (e) {}
    return '';
  }

  function normalizeLang(raw) {
    const normalized = String(raw || 'ru').toLowerCase().replace('_', '-');
    const base = normalized.split('-')[0];
    if (SUPPORTED_LANGS.indexOf(normalized) !== -1) return normalized;
    if (SUPPORTED_LANGS.indexOf(base) !== -1) return base;
    // Common aliases: keep mapping explicit for predictable behavior.
    if (normalized === 'pt-br') return 'pt';
    if (normalized === 'zh-cn' || normalized === 'zh-hans') return 'zh';
    if (base === 'zh') return 'zh';
    if (base === 'fil') return 'tl';
    if (base === 'iw') return 'he';
    if (base === 'in') return 'id';
    if (base === 'mo') return 'ro';
    return 'ru';
  }

  async function loadI18n() {
    currentLang = normalizeLang(detectPreferredLang());
    try {
      const res = await fetch('/i18n/' + currentLang + '.json', { cache: 'no-store' });
      if (!res.ok) throw new Error('i18n not available');
      i18nMessages = await res.json();
    } catch (e) {
      currentLang = 'en';
      try {
        const fallbackEn = await fetch('/i18n/en.json', { cache: 'no-store' });
        if (fallbackEn.ok) {
          i18nMessages = await fallbackEn.json();
          return;
        }
      } catch (err) {}
      const fallbackRu = await fetch('/i18n/ru.json', { cache: 'no-store' });
      i18nMessages = fallbackRu.ok ? await fallbackRu.json() : {};
    }
  }

  function applyStaticTexts() {
    const mobileText = document.querySelector('.mobile-only-text');
    const mobileHint = document.querySelector('.mobile-only-hint');
    const subtitle = document.querySelector('#lobby-screen .subtitle');
    const movesHeader = document.querySelector('.moves-header');
    if (mobileText) mobileText.textContent = t('mobile.open_on_phone');
    if (mobileHint) mobileHint.textContent = t('mobile.unsupported');
    if (subtitle) subtitle.textContent = t('lobby.subtitle');
    if (movesHeader) movesHeader.textContent = t('game.moves');
    if (btnFlipBoard) btnFlipBoard.textContent = t('game.flip');
    if (btnDraw) btnDraw.textContent = t('game.draw_offer');
    if (btnClaimDraw) btnClaimDraw.textContent = t('game.claim_draw');
    if (btnPrivateGame) btnPrivateGame.textContent = t('lobby.private_game');
    if (btnBotGame) btnBotGame.textContent = t('lobby.bot_game');
    if (btnProfile) btnProfile.textContent = t('profile.open');
    if (btnLogin) btnLogin.textContent = t('login.open');
    if (profileTitleEl) profileTitleEl.textContent = t('profile.title');
    if (btnLoginSubmit) btnLoginSubmit.textContent = t('login.submit');
    if (btnProfileClose) btnProfileClose.textContent = t('common.close');
    if (privateWaitingTitleEl) privateWaitingTitleEl.textContent = t('lobby.private_room_title');
    if (btnPrivateTimeClose) btnPrivateTimeClose.textContent = t('common.cancel');
    if (btnResign && !resignConfirming) btnResign.textContent = t('game.resign');
    if (resultModalTitleEl) resultModalTitleEl.textContent = t('result.title');
    if (btnResultLobby) btnResultLobby.textContent = t('result.back_to_lobby');
    if (btnResultAnalysis) btnResultAnalysis.textContent = t('result.analysis');
    if (btnResultRematch) btnResultRematch.textContent = t('result.rematch');
    if (btnBackGame) btnBackGame.setAttribute('aria-label', t('result.back_to_lobby'));
    if (gameInfo && !currentGameId) gameInfo.textContent = t('game.header');
    if (wsStatus && (!ws || ws.readyState !== WebSocket.OPEN)) setWsStatus(t('status.connecting'));
    updatePingIndicator();
  }

  function updatePingIndicator() {
    if (!pingIndicatorEl) return;
    if (pingMs == null) {
      pingIndicatorEl.textContent = t('game.ping', { ms: '—' });
      return;
    }
    pingIndicatorEl.textContent = t('game.ping', { ms: String(pingMs) });
  }

  function sendPingProbe() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'ping', client_ts: Date.now() }));
  }

  async function loadBuildInfo() {
    if (!buildInfoEl) return;
    try {
      const res = await fetch('/build-meta.json', { cache: 'no-store' });
      if (!res.ok) throw new Error('build meta not available');
      const meta = await res.json();
      const version = meta.version || t('build.unknown');
      const deployedAt = meta.deployed_at || t('build.unknown');
      buildInfoEl.textContent = t('build.label', { version: version, deployedAt: deployedAt });
    } catch (e) {
      buildInfoEl.textContent = t('build.label', { version: t('build.unknown'), deployedAt: t('build.unknown') });
    }
  }

  function resolveTelegramId() {
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      const uid = tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.id;
      if (uid) return Number(uid) || 0;
    } catch (e) {}
    return 0;
  }

  async function loadProfile() {
    const uid = myTelegramId || resolveTelegramId();
    if (!uid) return null;
    try {
      const res = await fetch('/api/profile?telegram_id=' + encodeURIComponent(uid), { cache: 'no-store' });
      if (!res.ok) return null;
      profileData = await res.json();
      if (btnLogin) btnLogin.style.display = profileData.is_anonymous ? '' : 'none';
      return profileData;
    } catch (e) {
      return null;
    }
  }

  async function loadHistory() {
    const uid = myTelegramId || resolveTelegramId();
    if (!uid) return [];
    try {
      const res = await fetch('/api/history?telegram_id=' + encodeURIComponent(uid), { cache: 'no-store' });
      if (!res.ok) return [];
      const data = await res.json();
      return data.items || [];
    } catch (e) {
      return [];
    }
  }

  async function loadTournamentHistory() {
    const uid = myTelegramId || resolveTelegramId();
    if (!uid) return [];
    try {
      const res = await fetch('/api/tournaments/history?telegram_id=' + encodeURIComponent(uid), { cache: 'no-store' });
      if (!res.ok) return [];
      const data = await res.json();
      return data.items || [];
    } catch (e) {
      return [];
    }
  }

  function closeProfileModal() {
    if (!profileModalEl) return;
    profileModalEl.classList.remove('active');
    profileModalEl.setAttribute('aria-hidden', 'true');
  }

  function openProfileModal() {
    if (!profileModalEl) return;
    const name = profileData && profileData.login_name ? profileData.login_name : t('profile.anonymous');
    const blitz = profileData && profileData.blitz_rating != null ? profileData.blitz_rating : 1500;
    const rapid = profileData && profileData.rapid_rating != null ? profileData.rapid_rating : 1500;
    const games = profileData && profileData.games_played != null ? profileData.games_played : 0;
    if (profileSummaryEl) profileSummaryEl.textContent = t('profile.summary', { name: name, blitz: blitz, rapid: rapid, games: games });
    if (loginFormWrapEl) loginFormWrapEl.style.display = (profileData && !profileData.is_anonymous) ? 'none' : '';
    if (profileHistoryEl) profileHistoryEl.textContent = '...';
    if (profileTournamentsEl) profileTournamentsEl.textContent = '...';
    profileModalEl.classList.add('active');
    profileModalEl.setAttribute('aria-hidden', 'false');
    loadTournamentHistory().then(function (titems) {
      if (!profileTournamentsEl) return;
      if (!titems.length) {
        profileTournamentsEl.textContent = '—';
        return;
      }
      profileTournamentsEl.innerHTML = titems.map(function (it) {
        const place = it.place != null ? ('место ' + it.place) : '—';
        const rw = it.reward_rank != null ? (' · награда ' + it.reward_rank) : '';
        return '<div class="mode-btn" style="cursor:default"><span>' + (it.format || '') + ' · ' + (it.time_control || '') +
          '</span><span class="queue-count">' + place + rw + '</span></div>';
      }).join('');
    });
    loadHistory().then(function (items) {
      if (!profileHistoryEl) return;
      if (!items.length) {
        profileHistoryEl.textContent = t('profile.history_empty');
        return;
      }
      profileHistoryEl.innerHTML = items.map(function (it) {
        const when = (it.created_at || '').slice(0, 19).replace('T', ' ');
        return '<button type="button" class="mode-btn" data-history-game="' + it.game_id + '"><span>' +
          (it.time_control || '') + ' · ' + (it.opponent || '') + '</span><span class="queue-count">' +
          when + ' · ' + (it.result || '-') + '</span></button>';
      }).join('');
      profileHistoryEl.querySelectorAll('[data-history-game]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          const gameId = btn.getAttribute('data-history-game');
          if (!gameId || !ws || ws.readyState !== WebSocket.OPEN) return;
          ws.send(JSON.stringify({ type: 'open_game_history', game_id: gameId }));
          closeProfileModal();
        });
      });
    });
  }

  async function submitLoginName() {
    if (!loginInputEl) return;
    const loginName = (loginInputEl.value || '').trim();
    if (!loginName) return;
    const uid = myTelegramId || resolveTelegramId();
    if (!uid) return;
    const res = await fetch('/api/login/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ telegram_id: uid, login_name: loginName }),
    });
    if (!res.ok) {
      setWsStatus(t('login.error'), 'error');
      return;
    }
    await loadProfile();
    openProfileModal();
  }

  function getInitData() {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
      return window.Telegram.WebApp.initData;
    }
    return '';
  }

  function getDebugUid() {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) return undefined;
    try {
      const key = 'phonechess_debug_uid';
      let v = localStorage.getItem(key);
      if (!v) {
        v = String(Math.floor(Math.random() * 1e9));
        localStorage.setItem(key, v);
      }
      return Number(v) || 1;
    } catch (e) {
      return 1;
    }
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

  function renderTournamentWaiting(tw) {
    tw = tw || {};
    const sw = tw.swiss || {};
    const ko = tw.ko || {};
    const tc = (tournamentTcSelectEl && tournamentTcSelectEl.value) ? tournamentTcSelectEl.value : '3+0';
    const ns = sw[tc] != null ? sw[tc] : 0;
    const nk = ko[tc] != null ? ko[tc] : 0;
    if (tourSwissCountEl) tourSwissCountEl.textContent = ns + ' в очереди';
    if (tourKoCountEl) tourKoCountEl.textContent = nk + ' в очереди';
  }

  function renderLobbyButtons(counts) {
    counts = counts || {};
    lobbyButtons.innerHTML = TIME_CONTROLS.map(key => {
      const n = counts[key] != null ? counts[key] : 0;
      const isYou = key === currentQueue;
      const countText = isYou ? t('lobby.queue_count_you', { n: n }) : t('lobby.queue_count', { n: n });
      const cls = isYou ? 'mode-btn in-queue' : 'mode-btn';
      return `<button type="button" class="${cls}" data-time="${key}"><span>${key}</span><span class="queue-count">${countText}</span></button>`;
    }).join('');
    lobbyButtons.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => onModeClick(btn.dataset.time));
    });
  }

  function hidePrivateWaitingPanel() {
    privateWaitingState = null;
    if (!privateWaitingPanelEl) return;
    privateWaitingPanelEl.classList.remove('active');
    if (lobbyButtons) lobbyButtons.style.display = '';
    if (btnPrivateGame) btnPrivateGame.style.display = '';
  }

  function showPrivateWaitingPanel(payload) {
    privateWaitingState = payload || null;
    if (!privateWaitingPanelEl || !privateWaitingTextEl) return;
    const role = payload && payload.role === 'guest' ? 'guest' : 'creator';
    const hasOpponent = !!(payload && payload.has_opponent);
    privateWaitingPanelEl.classList.add('active');
    if (lobbyButtons) lobbyButtons.style.display = 'none';
    if (btnPrivateGame) btnPrivateGame.style.display = 'none';
    if (privateWaitingTitleEl) privateWaitingTitleEl.textContent = t('lobby.private_room_title');
    if (role === 'creator') {
      privateWaitingTextEl.textContent = hasOpponent ? t('lobby.private_room_creator_ready') : t('lobby.private_room_creator_wait');
    } else {
      privateWaitingTextEl.textContent = hasOpponent ? t('lobby.private_room_guest_ready') : t('lobby.private_room_guest_wait');
    }
  }

  function openPrivateTimeModal() {
    if (!privateTimeModalEl || !privateTimeGridEl) return;
    privateTimeGridEl.innerHTML = TIME_CONTROLS.map(function (tc) {
      return '<button type="button" class="mode-btn" data-private-time="' + tc + '"><span>' + tc + '</span></button>';
    }).join('');
    privateTimeGridEl.querySelectorAll('[data-private-time]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const tc = btn.getAttribute('data-private-time');
        closePrivateTimeModal();
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({ type: 'create_private_invite', time_control: tc }));
      });
    });
    privateTimeModalEl.classList.add('active');
    privateTimeModalEl.setAttribute('aria-hidden', 'false');
  }

  function closePrivateTimeModal() {
    if (!privateTimeModalEl) return;
    privateTimeModalEl.classList.remove('active');
    privateTimeModalEl.setAttribute('aria-hidden', 'true');
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
    if (ms < 20000) {
      const total = Math.max(0, Math.ceil(ms));
      const m = Math.floor(total / 60000);
      const sec = Math.floor((total % 60000) / 1000);
      const secStr = (sec < 10 ? '0' : '') + sec;
      const tenth = Math.floor((total % 1000) / 100);
      return m + ':' + secStr + '.' + tenth;
    }
    const s = Math.ceil(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }

  function updateClocksDisplay() {
    const isWhite = myColor === 'white';
    const topMs = isWhite ? blackRemainingMs : whiteRemainingMs;
    const bottomMs = isWhite ? whiteRemainingMs : blackRemainingMs;
    const turnColor = gameFen && gameFen.includes(' b ') ? 'black' : 'white';
    const ourTurn = turnColor === myColor;
    const topIsActive = isWhite ? turnColor === 'black' : turnColor === 'white';
    const bottomIsActive = !topIsActive;
    const ourNoClock =
      isBotGame ||
      !!(noClockUserId && myTelegramId && String(noClockUserId) === String(myTelegramId));
    if (clockTopLabel) clockTopLabel.textContent = isWhite ? t('game.opp_black') : t('game.opp_white');
    if (clockBottomLabel) clockBottomLabel.textContent = isWhite ? t('game.you_white') : t('game.you_black');
    if (gameYourSideEl) {
      gameYourSideEl.textContent = fiftyMoveCounterText();
    }
    if (clockTop) {
      const topNoClock = isBotGame;
      clockTop.textContent = topNoClock ? '∞' : formatClock(topMs);
      clockTop.classList.toggle('low-time', !isBotGame && topMs < 20000 && topMs > 0);
      clockTop.classList.toggle('opp-turn', topIsActive && !gameResult);
      clockTop.classList.toggle('flagged', !isBotGame && topMs <= 0);
    }
    if (clockBottom) {
      const bottomNoClock = ourNoClock;
      clockBottom.textContent = bottomNoClock ? '∞' : formatClock(bottomMs);
      clockBottom.classList.toggle('low-time', !isBotGame && bottomMs < 20000 && bottomMs > 0);
      clockBottom.classList.toggle('our-turn', bottomIsActive && ourTurn && !gameResult);
      clockBottom.classList.toggle('flagged', !isBotGame && bottomMs <= 0);
    }
  }

  function updateReplayControls() {
    const active = replayMode && replayFens.length > 0;
    if (btnReplayFirst) btnReplayFirst.style.display = active ? '' : 'none';
    if (btnReplayPrev) btnReplayPrev.style.display = active ? '' : 'none';
    if (btnReplayNext) btnReplayNext.style.display = active ? '' : 'none';
    if (btnReplayLast) btnReplayLast.style.display = active ? '' : 'none';
    if (!active) return;
    if (btnReplayFirst) btnReplayFirst.disabled = replayIndex <= 0;
    if (btnReplayPrev) btnReplayPrev.disabled = replayIndex <= 0;
    if (btnReplayNext) btnReplayNext.disabled = replayIndex >= replayFens.length - 1;
    if (btnReplayLast) btnReplayLast.disabled = replayIndex >= replayFens.length - 1;
  }

  function hideResultModal() {
    if (!resultModalEl) return;
    resultModalEl.classList.remove('active');
    resultModalEl.setAttribute('aria-hidden', 'true');
    const card = resultModalEl.querySelector('.result-modal-card');
    if (card) card.classList.remove('result-white', 'result-black', 'result-draw');
  }

  function goToLobbyFromGame() {
    if (clockInterval) clearInterval(clockInterval);
    clockInterval = null;
    currentGameId = null;
    isBotGame = false;
    noClockUserId = null;
    rematchAvailableGameId = null;
    drawOfferBy = null;
    drawOfferColor = null;
    drawOfferPly = null;
    opponentDisconnected = false;
    opponentDisconnectedVisible = false;
    opponentDisconnectGraceSeconds = 0;
    if (opponentDisconnectDebounceTimer) {
      clearTimeout(opponentDisconnectDebounceTimer);
      opponentDisconnectDebounceTimer = null;
    }
    hideResultModal();
    replayMode = false;
    replayFens = [];
    replayMoves = [];
    replayIndex = -1;
    stopAnalysis();
    updateReplayControls();
    hidePrivateWaitingPanel();
    pingMs = null;
    updatePingIndicator();
    if (materialCapturedTopEl) materialCapturedTopEl.innerHTML = '';
    if (materialCapturedBottomEl) materialCapturedBottomEl.innerHTML = '';
    if (materialBalanceCenterEl) materialBalanceCenterEl.innerHTML = '';
    showScreen('lobby-screen');
  }

  function resultWinnerColor() {
    if (gameResult === '1-0') return 'white';
    if (gameResult === '0-1') return 'black';
    return null;
  }

  function resultTitleText() {
    const winner = resultWinnerColor();
    if (!winner) return t('result.draw_title');
    const colorWord = winner === 'white' ? t('result.color_white') : t('result.color_black');
    return t('result.title_win_by_color', { color: colorWord });
  }

  function resultSubtitleText() {
    if (gameResult === '1/2-1/2') return t('result.draw_subtitle');
    if (resultReason === 'timeout') return t('result.win_by_time');
    if (resultReason === 'checkmate') return t('result.win_by_checkmate');
    if (resultReason === 'resign') return t('result.win_by_resign');
    const reason = resultReasonText();
    if (reason) return reason;
    return t('result.win_generic');
  }

  function resultReasonText() {
    if (resultDetail) return resultDetail;
    switch (resultReason) {
      case 'checkmate': return t('reasons.checkmate');
      case 'timeout': return t('reasons.timeout');
      case 'stalemate': return t('reasons.stalemate');
      case 'insufficient_material': return t('reasons.insufficient_material');
      case 'draw_agreement': return t('reasons.draw_agreement');
      case 'draw_claim_threefold': return t('reasons.draw_claim_threefold');
      case 'draw_claim_fifty_move': return t('reasons.draw_claim_fifty_move');
      case 'draw_auto_fivefold': return t('reasons.draw_auto_fivefold');
      case 'draw_auto_75move': return t('reasons.draw_auto_75move');
      case 'disconnect_forfeit': return t('reasons.disconnect_forfeit');
      case 'disconnect_turn_timeout': return t('reasons.disconnect_turn_timeout');
      case 'resign': return t('reasons.resign');
      case 'aborted_unstarted': return t('reasons.aborted_unstarted');
      default: return '';
    }
  }

  function showResultModal() {
    if (!resultModalEl || !resultModalTextEl || !gameResult) return;
    if (resultModalTitleEl) resultModalTitleEl.textContent = resultTitleText();
    resultModalTextEl.textContent = resultSubtitleText();
    const card = resultModalEl.querySelector('.result-modal-card');
    if (card) {
      card.classList.remove('result-white', 'result-black', 'result-draw');
      const winner = resultWinnerColor();
      card.classList.add(winner ? ('result-' + winner) : 'result-draw');
    }
    resultModalEl.classList.add('active');
    resultModalEl.setAttribute('aria-hidden', 'false');
    if (btnResultRematch) {
      btnResultRematch.style.display = (resultReason === 'aborted_unstarted' && currentGameId) ? '' : 'none';
    }
    if (btnResultAnalysis) {
      btnResultAnalysis.style.display = replayFens && replayFens.length > 1 ? '' : 'none';
    }
  }

  function updateGameAlert() {
    if (!gameAlertEl) return;
    if (opponentDisconnectedVisible && !gameResult) {
      const sec = Math.max(0, Math.ceil(opponentDisconnectGraceSeconds));
      gameAlertEl.textContent = t('game.opp_disconnected', { sec: sec });
      gameAlertEl.className = 'game-alert active warning';
      return;
    }
    if (drawOfferBy && currentGameId && !gameResult) {
      if (drawOfferColor === myColor) {
        gameAlertEl.textContent = t('game.draw_offer_waiting');
      } else {
        gameAlertEl.textContent = t('game.draw_offer_received');
      }
      gameAlertEl.className = 'game-alert active info';
      return;
    }
    gameAlertEl.textContent = '';
    gameAlertEl.className = 'game-alert';
  }

  function updateDrawButton() {
    if (!btnDraw) return;
    if (isBotGame) {
      btnDraw.style.display = 'none';
      return;
    }
    if (!currentGameId || gameResult || replayMode) {
      btnDraw.style.display = 'none';
      return;
    }
    const ourCode = myColor === 'white' ? 'white' : 'black';
    const completedPlies = gameMoves.length;
    const showButton = completedPlies >= 30 || (drawOfferBy && drawOfferColor !== ourCode);
    if (!showButton) {
      btnDraw.style.display = 'none';
      return;
    }
    btnDraw.style.display = '';
    btnDraw.disabled = false;
    btnDraw.classList.remove('draw-pending');
    if (drawOfferBy) {
      if (drawOfferColor === ourCode) {
        btnDraw.textContent = t('game.draw_offer_sent');
        btnDraw.disabled = true;
        btnDraw.classList.add('draw-pending');
      } else {
        btnDraw.textContent = t('game.draw_offer');
      }
      return;
    }
    if (completedPlies < 30) {
      btnDraw.textContent = t('game.draw_offer');
      btnDraw.disabled = true;
      return;
    }
    btnDraw.textContent = t('game.draw_offer');
  }

  function canClaimDrawByRules() {
    return null;
  }

  function fiftyMoveCounterText() {
    if (!gameFen || gameResult) return '';
    const parts = gameFen.split(' ');
    const halfMoveClock = parts.length >= 5 ? parseInt(parts[4], 10) : 0;
    if (!Number.isFinite(halfMoveClock) || halfMoveClock < 40) return '';
    const fullMoves = Math.floor(halfMoveClock / 2);
    const text = t('game.fifty_counter', { n: fullMoves });
    return text === 'game.fifty_counter' ? (fullMoves + '/50') : text;
  }

  function updateClaimDrawButton() {
    if (!btnClaimDraw) return;
    btnClaimDraw.style.display = 'none';
  }

  function getReplayFenAt(index) {
    if (!replayMode || index < 0 || index >= replayFens.length) return null;
    return replayFens[index];
  }

  function setReplayIndex(index) {
    if (!replayMode) return;
    const next = Math.max(0, Math.min(index, replayFens.length - 1));
    replayIndex = next;
    const fen = getReplayFenAt(replayIndex);
    if (fen) {
      gameFen = fen;
      renderBoard();
      updateClocksDisplay();
      updateReplayControls();
      if (analysisEnabled) scheduleAnalysis();
    }
  }

  function enterReplayMode(history) {
    replayMode = true;
    currentGameId = history.game_id || null;
    gameResult = history.result || '1/2-1/2';
    resultReason = history.result_reason || null;
    resultDetail = history.result_detail || null;
    replayMoves = history.moves || [];
    replayFens = [];
    const startFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
    replayFens.push(startFen);
    for (let i = 0; i < replayMoves.length; i++) {
      const fenAfter = replayMoves[i].fen_after;
      if (fenAfter) replayFens.push(fenAfter);
    }
    if (!replayFens.length) replayFens = [history.fen || startFen];
    replayIndex = replayFens.length - 1;
    gameFen = replayFens[replayIndex];
    gameMoves = replayMoves.map(function (m) { return { san: m.san, time_ms: m.time_ms || 0 }; });
    showScreen('game-screen');
    renderMoveList();
    updateReplayControls();
    updateDrawButton();
    updateClaimDrawButton();
    if (analysisPanelEl) analysisPanelEl.classList.add('active');
    renderBoard();
    updateClocksDisplay();
  }

  function ensureStockfish() {
    if (stockfishWorker) return stockfishWorker;
    try {
      stockfishWorker = new Worker('https://cdn.jsdelivr.net/npm/stockfish/stockfish.js');
      stockfishWorker.onmessage = function (ev) {
        const line = String(ev.data || '');
        if (line.indexOf('score cp ') !== -1) {
          const m = /score cp (-?\d+)/.exec(line);
          if (m && analysisScoreEl) analysisScoreEl.textContent = (parseInt(m[1], 10) / 100).toFixed(2);
        } else if (line.indexOf('score mate ') !== -1) {
          const m2 = /score mate (-?\d+)/.exec(line);
          if (m2 && analysisScoreEl) analysisScoreEl.textContent = '#'+m2[1];
        }
        if (line.indexOf(' pv ') !== -1 && analysisLineEl) {
          const pv = line.split(' pv ')[1] || '';
          analysisLineEl.textContent = pv || '—';
        }
      };
    } catch (e) {
      stockfishWorker = null;
    }
    return stockfishWorker;
  }

  function analyzeCurrentPosition() {
    const fen = replayMode ? getReplayFenAt(replayIndex) : gameFen;
    if (!analysisEnabled || !fen) return;
    const reqId = ++analysisRequestId;
    fetch('/api/analyze?fen=' + encodeURIComponent(fen), { cache: 'no-store' })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!analysisEnabled || reqId !== analysisRequestId || !data) return;
        if (analysisScoreEl) {
          if (data.score_type === 'mate') analysisScoreEl.textContent = '#' + String(data.score || 0);
          else analysisScoreEl.textContent = (Number(data.score || 0) / 100).toFixed(2);
        }
        if (analysisLineEl) analysisLineEl.textContent = (data.pv || []).join(' ') || '—';
      })
      .catch(function () {
        const sf = ensureStockfish();
        if (!sf) {
          if (analysisLineEl) analysisLineEl.textContent = t('analysis.unavailable');
          return;
        }
        sf.postMessage('stop');
        sf.postMessage('position fen ' + fen);
        sf.postMessage('go depth 14');
      });
  }

  function scheduleAnalysis() {
    if (analysisDebounceTimer) {
      clearTimeout(analysisDebounceTimer);
      analysisDebounceTimer = null;
    }
    // Debounce replay scrubbing bursts to protect backend analysis endpoint.
    analysisDebounceTimer = setTimeout(function () {
      analysisDebounceTimer = null;
      analyzeCurrentPosition();
    }, 180);
  }

  function stopAnalysis() {
    analysisEnabled = false;
    if (btnAnalysisToggle) btnAnalysisToggle.textContent = t('analysis.start');
    if (analysisDebounceTimer) {
      clearTimeout(analysisDebounceTimer);
      analysisDebounceTimer = null;
    }
    if (stockfishWorker) {
      try { stockfishWorker.postMessage('stop'); } catch (e) {}
    }
  }

  function tickClocks() {
    if (gameResult) return;
    const now = Date.now();
    const fen = gameFen;
    if (!fen) return;
    const turn = fen.includes(' w ') ? 'white' : 'black';
    if (lastClockTick > 0 && !isBotGame) {
      const elapsed = Math.min(now - lastClockTick, 1000);
      if (turn === 'white') whiteRemainingMs = Math.max(0, whiteRemainingMs - elapsed);
      else blackRemainingMs = Math.max(0, blackRemainingMs - elapsed);
      if (opponentDisconnected && opponentDisconnectGraceSeconds > 0) {
        opponentDisconnectGraceSeconds = Math.max(0, opponentDisconnectGraceSeconds - (elapsed / 1000));
      }
    }
    lastClockTick = now;
    requestGameStateSync(now);
    updateGameAlert();
    updateClocksDisplay();
  }

  function requestGameStateSync(nowMs) {
    const now = nowMs != null ? nowMs : Date.now();
    if (!currentGameId || !ws || ws.readyState !== WebSocket.OPEN) return;
    if (now - lastStateSyncAt < STATE_RESYNC_MS) return;
    ws.send(JSON.stringify({ type: 'subscribe_game', game_id: currentGameId }));
    lastStateSyncAt = now;
  }

  function startClockTicker() {
    if (clockInterval) clearInterval(clockInterval);
    lastClockTick = Date.now();
    updateClocksDisplay();
    clockInterval = setInterval(tickClocks, 33);
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

  function boardToFenPlacement(board) {
    const rows = [];
    for (let r = 0; r < 8; r++) {
      let row = '';
      let empties = 0;
      for (let c = 0; c < 8; c++) {
        const p = board[r] && board[r][c];
        if (!p) {
          empties++;
        } else {
          if (empties > 0) row += String(empties);
          empties = 0;
          row += p;
        }
      }
      if (empties > 0) row += String(empties);
      rows.push(row);
    }
    return rows.join('/');
  }

  function squareToBoardCoords(square) {
    if (!square || square.length < 2) return null;
    const file = FILES.indexOf(square[0]);
    const rank = parseInt(square[1], 10);
    if (file < 0 || rank < 1 || rank > 8) return null;
    return { row: 8 - rank, col: file };
  }

  function boardCoordsToSquare(row, col) {
    if (row < 0 || row > 7 || col < 0 || col > 7) return null;
    return FILES[col] + (8 - row);
  }

  function inBoard(row, col) {
    return row >= 0 && row < 8 && col >= 0 && col < 8;
  }

  function pieceColorFromFenLetter(letter) {
    if (!letter) return null;
    return letter === letter.toUpperCase() ? 'white' : 'black';
  }

  function getPieceAtSquareFromFen(fen, square) {
    const coords = squareToBoardCoords(square);
    if (!coords) return null;
    const board = parseFenPieces(fen);
    return (board[coords.row] && board[coords.row][coords.col]) || null;
  }

  function pseudoTargetsFromSquareForColor(fen, square, color) {
    const coords = squareToBoardCoords(square);
    if (!coords) return [];
    const board = parseFenPieces(fen);
    const piece = board[coords.row] && board[coords.row][coords.col];
    if (!piece || pieceColorFromFenLetter(piece) !== color) return [];
    const enemyColor = color === 'white' ? 'black' : 'white';
    const targets = [];
    const addStep = function (row, col) {
      if (!inBoard(row, col)) return;
      const targetPiece = board[row] && board[row][col];
      const targetColor = pieceColorFromFenLetter(targetPiece);
      const sq = boardCoordsToSquare(row, col);
      if (sq) targets.push(sq);
      return targetColor !== null;
    };
    const addSlide = function (dr, dc) {
      let row = coords.row + dr;
      let col = coords.col + dc;
      while (inBoard(row, col)) {
        const sq = boardCoordsToSquare(row, col);
        if (sq) targets.push(sq);
        row += dr;
        col += dc;
      }
    };

    switch (piece.toUpperCase()) {
      case 'P': {
        const dir = color === 'white' ? -1 : 1;
        const startRow = color === 'white' ? 6 : 1;
        const oneRow = coords.row + dir;
        if (inBoard(oneRow, coords.col) && !(board[oneRow] && board[oneRow][coords.col])) {
          addStep(oneRow, coords.col);
          const twoRow = coords.row + dir * 2;
          if (coords.row === startRow && inBoard(twoRow, coords.col) && !(board[twoRow] && board[twoRow][coords.col])) {
            addStep(twoRow, coords.col);
          }
        }
        [coords.col - 1, coords.col + 1].forEach(function (captureCol) {
          if (!inBoard(oneRow, captureCol)) return;
          const sq = boardCoordsToSquare(oneRow, captureCol);
          if (sq) targets.push(sq);
        });
        break;
      }
      case 'N':
        [[-2, -1], [-2, 1], [-1, -2], [-1, 2], [1, -2], [1, 2], [2, -1], [2, 1]].forEach(function (d) {
          addStep(coords.row + d[0], coords.col + d[1]);
        });
        break;
      case 'B':
        [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(function (d) { addSlide(d[0], d[1]); });
        break;
      case 'R':
        [[-1, 0], [1, 0], [0, -1], [0, 1]].forEach(function (d) { addSlide(d[0], d[1]); });
        break;
      case 'Q':
        [[-1, -1], [-1, 1], [1, -1], [1, 1], [-1, 0], [1, 0], [0, -1], [0, 1]].forEach(function (d) { addSlide(d[0], d[1]); });
        break;
      case 'K':
        [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]].forEach(function (d) {
          addStep(coords.row + d[0], coords.col + d[1]);
        });
        break;
    }
    return targets;
  }

  function applyPseudoMoveToFen(fen, fromSq, toSq, color, promotion) {
    const from = squareToBoardCoords(fromSq);
    const to = squareToBoardCoords(toSq);
    if (!from || !to) return fen;
    const parts = (fen || '').split(' ');
    const board = parseFenPieces(fen);
    const piece = board[from.row] && board[from.row][from.col];
    if (!piece || pieceColorFromFenLetter(piece) !== color) return fen;
    board[from.row][from.col] = null;
    let nextPiece = piece;
    if (piece.toUpperCase() === 'P' && ((color === 'white' && to.row === 0) || (color === 'black' && to.row === 7))) {
      const promo = (promotion || 'q').toLowerCase();
      nextPiece = color === 'white' ? promo.toUpperCase() : promo;
    }
    board[to.row][to.col] = nextPiece;
    parts[0] = boardToFenPlacement(board);
    if (parts.length >= 2) parts[1] = color === 'white' ? 'b' : 'w';
    return parts.join(' ');
  }

  function getBoardRowByDisplayRow(displayRow, orientation) {
    return orientation === 'black' ? 7 - displayRow : displayRow;
  }

  function getBoardColByDisplayCol(displayCol, orientation) {
    return orientation === 'black' ? 7 - displayCol : displayCol;
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
    const boardForDisplayFen = getPreviewFenFromPremoves(gameFen);
    const board = parseFenPieces(boardForDisplayFen);
    boardEl.innerHTML = '';
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const br = getBoardRowByDisplayRow(row, effectiveOrientation);
        const bc = getBoardColByDisplayCol(col, effectiveOrientation);
        const piece = board[br] && board[br][bc];
        const isLight = (row + col) % 2 === 0;
        const sq = FILES[bc] + (8 - br);
        const div = document.createElement('div');
        div.className = 'square ' + (isLight ? 'light' : 'dark');
        div.dataset.square = sq;
        if (row === 7) {
          const fileLabel = document.createElement('span');
          fileLabel.className = 'coord-file';
          fileLabel.textContent = sq[0];
          div.appendChild(fileLabel);
        }
        if (col === 0) {
          const rankLabel = document.createElement('span');
          rankLabel.className = 'coord-rank';
          rankLabel.textContent = sq[1];
          div.appendChild(rankLabel);
        }
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
        const pieceEl = div.querySelector('.piece-sprite');
        draggedSquare = sq;
        selectSquare(sq, 'drag');
        e.dataTransfer.setData('text/plain', sq);
        e.dataTransfer.effectAllowed = 'move';
        if (pieceEl) {
          // Drag preview should be just the piece, not the whole square.
          e.dataTransfer.setDragImage(pieceEl, pieceEl.offsetWidth / 2, pieceEl.offsetHeight / 2);
        }
        div.classList.add('dragging-source');
        applyLegalTargetsToCurrentBoard();
      });
      div.addEventListener('dragend', function () {
        div.classList.remove('dragging-source');
        draggedSquare = null;
        clearSelection();
        applyLegalTargetsToCurrentBoard();
      });
    }
        div.addEventListener('dragover', function (e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; });
        div.addEventListener('drop', function (e) {
          e.preventDefault();
          if (draggedSquare && draggedSquare !== sq) doMoveFromTo(draggedSquare, sq);
          draggedSquare = null;
        });
        if (lastMove && (lastMove.from === sq || lastMove.to === sq)) div.classList.add('last-move');
        let premoveFromIndex = -1;
        let premoveToIndex = -1;
        for (let pmi = 0; pmi < premoveQueue.length; pmi++) {
          const pm = premoveQueue[pmi];
          if (pm.from === sq) premoveFromIndex = pmi;
          if (pm.to === sq) premoveToIndex = pmi;
        }
        if (premoveFromIndex !== -1) {
          div.classList.add('premove-from');
          div.style.setProperty('--premove-color', PREMOVE_COLORS[premoveFromIndex % PREMOVE_COLORS.length]);
        }
        if (premoveToIndex !== -1) {
          div.classList.add('premove-to');
          div.style.setProperty('--premove-color', PREMOVE_COLORS[premoveToIndex % PREMOVE_COLORS.length]);
          div.dataset.premoveStep = String(premoveToIndex + 1);
        }
        if (selectedSquare === sq) div.classList.add('selected');
        if (touchDragTargetSquare === sq) div.classList.add('drag-hover');
        if (legalTargets.indexOf(sq) !== -1) {
          div.classList.add('legal');
          div.classList.add(legalTargetsMode === 'tap' ? 'legal-tap' : 'legal-drag');
        }
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
      cell.addEventListener('dblclick', function () { clearPremoves(); });
      cell.addEventListener('touchstart', function (e) {
        if (!currentGameId || !gameFen || gameResult || replayMode) return;
        const ourTurn = turnFromFen(gameFen) === myColor;
        const sourceFen = ourTurn ? gameFen : getPreviewFenFromPremoves(gameFen);
        const p = getPieceAtSquareFromFen(sourceFen, sq);
        if (!p || pieceColorFromFenLetter(p) !== myColor) return;
        touchDragFromSquare = sq;
        touchDragTargetSquare = sq;
        touchDragMoved = false;
        selectSquare(sq, 'drag');
        renderBoard();
      }, { passive: true });
      cell.addEventListener('touchmove', function (e) {
        if (!touchDragFromSquare) return;
        if (!e.changedTouches || !e.changedTouches.length) return;
        e.preventDefault();
        const t = e.changedTouches[0];
        const el = document.elementFromPoint(t.clientX, t.clientY);
        const target = el && el.closest ? el.closest('.square') : null;
        if (!target || !target.dataset.square) return;
        touchDragMoved = true;
        if (touchDragTargetSquare !== target.dataset.square) {
          touchDragTargetSquare = target.dataset.square;
          renderBoard();
        }
      }, { passive: false });
      cell.addEventListener('touchend', function (e) {
        e.preventDefault();
        const touchFromSquare = touchDragFromSquare;
        if (touchDragFromSquare) {
          const fromSq = touchDragFromSquare;
          const toSq = touchDragTargetSquare;
          touchDragFromSquare = null;
          touchDragTargetSquare = null;
          if (touchDragMoved && toSq && toSq !== fromSq) {
            doMoveFromTo(fromSq, toSq);
            touchDragMoved = false;
            return;
          }
          touchDragMoved = false;
        }
        const now = Date.now();
        if (now - lastTouchTapAt < 320 && lastTouchTapSquare === sq) {
          clearPremoves();
          lastTouchTapAt = 0;
          lastTouchTapSquare = null;
          return;
        }
        lastTouchTapAt = now;
        lastTouchTapSquare = sq;
        if (touchFromSquare && touchFromSquare === sq) {
          const ctx = getInputContext();
          const p = getPieceAtSquareFromFen(ctx.fenForPieces, sq);
          const mine = !!p && pieceColorFromFenLetter(p) === myColor;
          if (mine) {
            if (selectedSquare === sq && legalTargetsMode === 'tap') {
              clearSelection();
            } else {
              selectSquare(sq, 'tap');
            }
            renderBoard();
            return;
          }
        }
        onSquareClick(sq);
      }, { passive: false });
    });
    updateMaterialAndBalance();
    } catch (e) {
      console.error('[PhoneChess] renderBoard error', e);
    }
  }

  function turnFromFen(fen) {
    return fen && fen.includes(' b ') ? 'black' : 'white';
  }

  function fenForColorTurn(fen, color) {
    if (!fen) return fen;
    const parts = fen.split(' ');
    if (parts.length >= 2) parts[1] = color === 'white' ? 'w' : 'b';
    return parts.join(' ');
  }

  function getPreviewFenFromPremoves(baseFen) {
    if (!baseFen || premoveQueue.length === 0) return baseFen;
    let fen = baseFen;
    for (let i = 0; i < premoveQueue.length; i++) {
      const pm = premoveQueue[i];
      const pseudoTargets = pseudoTargetsFromSquareForColor(fen, pm.from, myColor);
      if (pseudoTargets.indexOf(pm.to) === -1) break;
      fen = applyPseudoMoveToFen(fen, pm.from, pm.to, myColor, pm.promotion || 'q');
    }
    return fen;
  }

  function getInputContext() {
    const ourTurn = turnFromFen(gameFen) === myColor;
    const previewFen = getPreviewFenFromPremoves(gameFen);
    return {
      ourTurn: ourTurn,
      fenForPieces: ourTurn ? gameFen : previewFen,
      fenForTargets: ourTurn ? gameFen : previewFen
    };
  }

  function getTargetsForSquare(square) {
    const ctx = getInputContext();
    if (ctx.ourTurn) {
      const moves = legalMovesFromSquareForColor(ctx.fenForTargets, square, myColor);
      return (moves || []).map(function (m) { return m.to; });
    }
    return pseudoTargetsFromSquareForColor(ctx.fenForTargets, square, myColor);
  }

  function clearSelection() {
    selectedSquare = null;
    legalTargets = [];
    legalTargetsMode = 'none';
  }

  function selectSquare(square, mode) {
    selectedSquare = square;
    legalTargets = getTargetsForSquare(square);
    legalTargetsMode = mode || 'tap';
  }

  function shouldAskPromotion(move) {
    return !!move && (move.flags || '').indexOf('p') !== -1;
  }

  function hidePromotionPicker() {
    pendingPromotionChoice = null;
    if (!promotionPickerEl) return;
    promotionPickerEl.classList.remove('active');
    promotionPickerEl.setAttribute('aria-hidden', 'true');
    if (promotionChoicesEl) promotionChoicesEl.innerHTML = '';
  }

  function submitMove(fromSq, toSq, promotion, isPremove) {
    if (isPremove) {
      queuePremove(fromSq, toSq, promotion);
    } else {
      applyOptimisticLocalMove(fromSq, toSq, promotion);
      ws.send(JSON.stringify({ type: 'make_move', game_id: currentGameId, from: fromSq, to: toSq, promotion: promotion || null }));
    }
    clearSelection();
    renderBoard();
  }

  function applyOptimisticLocalMove(fromSq, toSq, promotion) {
    if (!gameFen || gameResult) return;
    try {
      const c = new Chess(gameFen);
      const m = c.move({ from: fromSq, to: toSq, promotion: promotion || undefined });
      if (!m) return;
      const now = Date.now();
      const elapsed = lastClockTick > 0 ? Math.max(0, now - lastClockTick) : 0;
      if (!isBotGame) {
        if (myColor === 'white') {
          whiteRemainingMs = Math.max(0, whiteRemainingMs - elapsed);
        } else if (myColor === 'black') {
          blackRemainingMs = Math.max(0, blackRemainingMs - elapsed);
        }
      }
      gameFen = c.fen();
      lastMove = { from: fromSq, to: toSq };
      lastClockTick = now;
      updateClocksDisplay();
    } catch (e) {}
  }

  function showPromotionPicker(fromSq, toSq, isPremove) {
    if (!promotionPickerEl || !promotionChoicesEl) {
      submitMove(fromSq, toSq, 'q', isPremove);
      return;
    }
    pendingPromotionChoice = { from: fromSq, to: toSq, isPremove: isPremove };
    const white = myColor === 'white';
    const options = white ? ['q', 'r', 'b', 'n'] : ['n', 'b', 'r', 'q'];
    promotionChoicesEl.innerHTML = '';
    options.forEach(function (opt) {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'promotion-choice';
      cell.dataset.promotion = opt;
      const wrap = document.createElement('div');
      wrap.className = 'piece-sprite';
      wrap.style.backgroundImage = 'url(' + PIECE_SPRITE_URL + ')';
      wrap.style.backgroundSize = '600% 200%';
      const pieceLetter = (white ? opt.toUpperCase() : opt);
      const off = pieceSpriteOffset(pieceLetter);
      wrap.style.backgroundPosition = (off.col * 20) + '% ' + (off.row * 100) + '%';
      cell.appendChild(wrap);
      promotionChoicesEl.appendChild(cell);
    });
    promotionPickerEl.classList.add('active');
    promotionPickerEl.setAttribute('aria-hidden', 'false');
  }

  function legalMovesFromSquareForColor(fen, square, color) {
    try {
      const c = new Chess(fenForColorTurn(fen, color));
      return c.moves({ square: square, verbose: true }) || [];
    } catch (e) {
      return [];
    }
  }

  function applyLegalTargetsToCurrentBoard() {
    if (!boardEl) return;
    const targets = legalTargets || [];
    boardEl.querySelectorAll('.square').forEach(function (cell) {
      const sq = cell.dataset.square;
      if (!sq) return;
      const on = targets.indexOf(sq) !== -1;
      cell.classList.toggle('legal', on);
      cell.classList.toggle('legal-tap', on && legalTargetsMode === 'tap');
      cell.classList.toggle('legal-drag', on && legalTargetsMode === 'drag');
    });
  }

  function clearPremoves() {
    premoveQueue = [];
    clearSelection();
    hidePromotionPicker();
    updateClocksDisplay();
    renderBoard();
  }

  function queuePremove(fromSq, toSq, promotion) {
    premoveQueue.push({ from: fromSq, to: toSq, promotion: promotion || null });
    updateClocksDisplay();
  }

  function tryExecutePremoves() {
    if (!currentGameId || !gameFen || gameResult) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (turnFromFen(gameFen) !== myColor) return;

    let sent = false;
    while (premoveQueue.length > 0 && !sent) {
      const pm = premoveQueue.shift();
      const moves = legalMovesFromSquareForColor(gameFen, pm.from, myColor);
      const move = moves.find(function (m) { return m.to === pm.to; });
      if (!move) {
        // If first premove is impossible in the new position, drop the whole chain.
        premoveQueue = [];
        updateClocksDisplay();
        break;
      }
      const promotion = pm.promotion || (((move.flags || '').indexOf('p') !== -1) ? 'q' : null);
      ws.send(JSON.stringify({ type: 'make_move', game_id: currentGameId, from: pm.from, to: pm.to, promotion: promotion, premove: true }));
      clearSelection();
      sent = true;
    }
    updateClocksDisplay();
    renderBoard();
  }

  function doMoveFromTo(fromSq, toSq) {
    if (!currentGameId || !gameFen || gameResult || replayMode) return;
    try {
      var c = new Chess(gameFen);
    } catch (e) { return; }
    var ourTurn = turnFromFen(gameFen) === myColor;
    if (ourTurn) {
      var moves = c.moves({ square: fromSq, verbose: true });
      var move = moves && moves.find(function (m) { return m.to === toSq; });
      if (!move) return;
      if (shouldAskPromotion(move)) {
        showPromotionPicker(fromSq, toSq, false);
        return;
      }
      submitMove(fromSq, toSq, null, false);
      return;
    }

    const previewFen = getPreviewFenFromPremoves(gameFen);
    const legalMoves = legalMovesFromSquareForColor(previewFen, fromSq, myColor);
    const legalMove = legalMoves && legalMoves.find(function (m) { return m.to === toSq; });
    const pseudoTargets = pseudoTargetsFromSquareForColor(previewFen, fromSq, myColor);
    if (!legalMove && pseudoTargets.indexOf(toSq) === -1) return;
    let asksPromotion = false;
    if (legalMove) {
      asksPromotion = shouldAskPromotion(legalMove);
    } else {
      try {
        const previewChess = new Chess(fenForColorTurn(previewFen, myColor));
        const piece = previewChess.get(fromSq);
        const rank = parseInt(toSq[1], 10);
        asksPromotion = !!piece && piece.type === 'p' && (rank === 1 || rank === 8);
      } catch (e) {}
    }
    if (asksPromotion) {
      showPromotionPicker(fromSq, toSq, true);
      return;
    }
    submitMove(fromSq, toSq, null, true);
  }

  function onSquareClick(sq) {
    if (!currentGameId || !gameFen || gameResult || replayMode) {
      console.log('[PhoneChess] onSquareClick early return: no game/fen/result');
      return;
    }
    var piece = null;
    try {
      var previewChess = new Chess(getInputContext().fenForPieces);
      piece = previewChess.get(sq);
    } catch (e) {
      console.error('[PhoneChess] onSquareClick Chess error', e);
      return;
    }
    var pieceColor = piece && typeof piece === 'object' ? piece.color : null;
    var myColorShort = myColor === 'white' ? 'w' : 'b';
    var mine = pieceColor && pieceColor === myColorShort;
    if (selectedSquare) {
      if (legalTargets.indexOf(sq) !== -1) {
        doMoveFromTo(selectedSquare, sq);
        return;
      }
      clearSelection();
    } else if (mine) {
      selectSquare(sq, 'tap');
    }
    renderBoard();
  }

  function pieceValueFromLetter(ch) {
    const v = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
    return v[String(ch || '').toLowerCase()] || 0;
  }

  function materialBalanceWhiteMinusBlack(fen) {
    if (!fen) return 0;
    const placement = fen.split(' ')[0];
    let w = 0;
    let b = 0;
    for (let i = 0; i < placement.length; i++) {
      const ch = placement[i];
      if (ch === '/') continue;
      if ('KQRBNP'.indexOf(ch) !== -1) w += pieceValueFromLetter(ch);
      if ('kqrbnp'.indexOf(ch) !== -1) b += pieceValueFromLetter(ch);
    }
    return w - b;
  }

  function sortCapturedTypes(types) {
    const order = { q: 5, r: 4, b: 3, n: 2, p: 1 };
    return types.slice().sort(function (a, b) { return (order[b] || 0) - (order[a] || 0); });
  }

  function renderCaptureGlyphs(types, capturedWhitePieces) {
    const whiteMap = { p: '\u2659', n: '\u2658', b: '\u2657', r: '\u2656', q: '\u2655' };
    const blackMap = { p: '\u265F', n: '\u265E', b: '\u265D', r: '\u265C', q: '\u265B' };
    const map = capturedWhitePieces ? whiteMap : blackMap;
    return sortCapturedTypes(types)
      .map(function (t) { return map[t] || ''; })
      .join('');
  }

  function computeCapturePockets(moves) {
    const byWhite = [];
    const byBlack = [];
    if (!moves || !moves.length || typeof window.Chess === 'undefined') {
      return { byWhite: byWhite, byBlack: byBlack };
    }
    const c = new window.Chess();
    for (let i = 0; i < moves.length; i++) {
      const san = moves[i].san;
      if (!san) continue;
      const m = c.move(san);
      if (!m) break;
      if (m.captured) {
        if (m.color === 'w') byWhite.push(m.captured);
        else byBlack.push(m.captured);
      }
    }
    return { byWhite: byWhite, byBlack: byBlack };
  }

  function effectiveMovesForMaterial() {
    if (!replayMode) return gameMoves;
    const k = Math.max(0, Math.min(replayIndex, gameMoves.length));
    return gameMoves.slice(0, k);
  }

  function rebuildReplayFensFromGameMoves() {
    replayFens = [];
    if (typeof window.Chess === 'undefined' || !gameMoves.length) return;
    const c = new window.Chess();
    replayFens.push(c.fen());
    for (let i = 0; i < gameMoves.length; i++) {
      if (!c.move(gameMoves[i].san)) break;
      replayFens.push(c.fen());
    }
  }

  function updateMaterialAndBalance() {
    if (!materialCapturedTopEl || !materialCapturedBottomEl || !materialBalanceCenterEl) return;
    if (!currentGameId || !gameFen) {
      materialCapturedTopEl.innerHTML = '';
      materialCapturedBottomEl.innerHTML = '';
      materialBalanceCenterEl.innerHTML = '';
      materialCapturedTopEl.setAttribute('aria-hidden', 'true');
      materialCapturedBottomEl.setAttribute('aria-hidden', 'true');
      materialBalanceCenterEl.setAttribute('aria-hidden', 'true');
      return;
    }
    const moves = effectiveMovesForMaterial();
    const pockets = computeCapturePockets(moves);
    const myCaps = myColor === 'white' ? pockets.byWhite : pockets.byBlack;
    const oppCaps = myColor === 'white' ? pockets.byBlack : pockets.byWhite;
    const balW = materialBalanceWhiteMinusBlack(gameFen);
    const balMine = myColor === 'white' ? balW : -balW;
    let balText = '0.0p';
    if (Math.abs(balMine) >= 0.05) {
      const sign = balMine >= 0 ? '+' : '\u2212';
      balText = sign + Math.abs(balMine).toFixed(1) + 'p';
    } else {
      balText = '0.0p';
    }
    materialCapturedTopEl.innerHTML =
      '<span class="material-pile">' + renderCaptureGlyphs(oppCaps, myColor === 'white') + '</span>';
    materialCapturedBottomEl.innerHTML =
      '<span class="material-pile">' + renderCaptureGlyphs(myCaps, myColor === 'black') + '</span>';
    materialBalanceCenterEl.innerHTML =
      '<span class="material-balance-val" title="">' + balText + '</span>';
    materialCapturedTopEl.setAttribute('aria-hidden', 'false');
    materialCapturedBottomEl.setAttribute('aria-hidden', 'false');
    materialBalanceCenterEl.setAttribute('aria-hidden', 'false');
  }

  function renderMoveList() {
    if (!moveListEl) return;
    function formatMoveDuration(ms) {
      const total = Math.max(0, ms | 0);
      const min = Math.floor(total / 60000);
      const sec = Math.floor((total % 60000) / 1000);
      const milli = total % 1000;
      if (min > 0) {
        return min + ':' + String(sec).padStart(2, '0') + '.' + String(milli).padStart(3, '0');
      }
      if (sec > 0) {
        return sec + '.' + String(milli).padStart(3, '0') + t('time.sec_short');
      }
      return milli + t('time.ms_short');
    }
    let html = '';
    let num = 1;
    for (let i = 0; i < gameMoves.length; i++) {
      const m = gameMoves[i];
      const timeStr = formatMoveDuration(m.time_ms);
      let sanDisp = m.san || '';
      if (i === gameMoves.length - 1 && gameResult && resultReason === 'checkmate' && sanDisp.indexOf('#') === -1) {
        sanDisp = sanDisp + '#';
      }
      if (i % 2 === 0) html += '<span class="move-num">' + num++ + '.</span> ';
      html += sanDisp + ' <span class="move-time">(' + timeStr + ')</span> ';
    }
    moveListEl.innerHTML = html || '—';
  }

  function applyGameState(data) {
    if (replayMode) return;
    console.log('[PhoneChess] applyGameState', { hasFen: !!data.fen, moves: data.moves?.length, result: data.result });
    const hadResultBefore = !!gameResult;
    gameFen = data.fen || gameFen;
    if (data.is_bot_game !== undefined) isBotGame = !!data.is_bot_game;
    whiteRemainingMs = data.white_remaining_ms != null ? data.white_remaining_ms : whiteRemainingMs;
    blackRemainingMs = data.black_remaining_ms != null ? data.black_remaining_ms : blackRemainingMs;
    if (data.server_time_ms != null && gameFen && !gameResult && !isBotGame) {
      const lag = Math.max(0, Math.min(2000, Date.now() - data.server_time_ms));
      const turnColor = gameFen.includes(' b ') ? 'black' : 'white';
      if (turnColor === 'white') whiteRemainingMs = Math.max(0, whiteRemainingMs - lag);
      else blackRemainingMs = Math.max(0, blackRemainingMs - lag);
    }
    if (data.moves) {
      gameMoves = (data.moves || []).map(function (m) {
        return { san: m.san, time_ms: m.time_ms != null ? m.time_ms : 0 };
      });
    } else if (data.san && data.move_time_ms !== undefined) {
      gameMoves = gameMoves.concat([{ san: data.san, time_ms: data.move_time_ms }]);
    }
    if (data.no_clock_user_id !== undefined) noClockUserId = data.no_clock_user_id || null;
    if (data.result !== undefined) gameResult = data.result;
    if (data.result_reason !== undefined) resultReason = data.result_reason;
    if (data.result_detail !== undefined) resultDetail = data.result_detail;
    if (data.draw_offer_by !== undefined) drawOfferBy = data.draw_offer_by;
    if (data.draw_offer_color !== undefined) drawOfferColor = data.draw_offer_color;
    if (data.from && data.to) lastMove = { from: data.from, to: data.to };
    if (!hadResultBefore && gameResult) {
      rebuildReplayFensFromGameMoves();
      replayMode = true;
      replayIndex = Math.max(0, replayFens.length - 1);
      gameFen = replayFens[replayIndex] || gameFen;
      if (analysisPanelEl) analysisPanelEl.classList.add('active');
      updateReplayControls();
    }
    updateClocksDisplay();
    startClockTicker();
    renderBoard();
    renderMoveList();
    tryExecutePremoves();
    updateDrawButton();
    updateClaimDrawButton();
    updateGameAlert();
    if (gameResult && gameInfo) {
      const r = gameResult === '1-0' ? t('game.white_won') : gameResult === '0-1' ? t('game.black_won') : t('game.draw');
      gameInfo.textContent = gameInfo.textContent + ' — ' + r;
      showResultModal();
    }
  }

  function enterGame(msg) {
    replayMode = false;
    replayFens = [];
    replayMoves = [];
    replayIndex = -1;
    stopAnalysis();
    if (analysisPanelEl) analysisPanelEl.classList.remove('active');
    updateReplayControls();
    console.log('[PhoneChess] enterGame', { game_id: msg.game_id, color: msg.color, hasFen: !!msg.fen });
    currentGameId = msg.game_id;
    rematchAvailableGameId = null;
    hidePrivateWaitingPanel();
    myColor = msg.color;
    isBotGame = !!msg.is_bot_game;
    noClockUserId = msg.no_clock_user_id || null;
    gameFen = msg.fen;
    whiteRemainingMs = msg.white_remaining_ms != null ? msg.white_remaining_ms : 0;
    blackRemainingMs = msg.black_remaining_ms != null ? msg.black_remaining_ms : 0;
    gameMoves = [];
    gameResult = null;
    clearSelection();
    lastMove = null;
    boardFlipped = false;
    premoveQueue = [];
    resultReason = null;
    resultDetail = null;
    drawOfferBy = null;
    drawOfferColor = null;
    drawOfferPly = null;
    opponentDisconnected = false;
    opponentDisconnectedVisible = false;
    opponentDisconnectGraceSeconds = 0;
    if (opponentDisconnectDebounceTimer) {
      clearTimeout(opponentDisconnectDebounceTimer);
      opponentDisconnectDebounceTimer = null;
    }
    lastStateSyncAt = 0;
    hidePromotionPicker();
    hideResultModal();
    updateClocksDisplay();
    if (resignConfirmTimeout) clearTimeout(resignConfirmTimeout);
    resignConfirming = false;
    if (btnResign) { btnResign.textContent = t('game.resign'); btnResign.classList.remove('resign-confirm'); }
    if (gameInfo) gameInfo.textContent = (msg.white_username || t('game.white_name')) + ' vs ' + (msg.black_username || t('game.black_name')) + ' (' + (msg.time_control || '') + ')';
    if (btnDraw) btnDraw.style.display = isBotGame ? 'none' : '';
    if (btnClaimDraw) btnClaimDraw.style.display = 'none';
    showScreen('game-screen');
    updatePingIndicator();
    updateClocksDisplay();
    startClockTicker();
    renderBoard();
    renderMoveList();
    updateDrawButton();
    updateClaimDrawButton();
    updateGameAlert();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe_game', game_id: currentGameId }));
    }
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    var wsUrl = API_URL + '/ws';
    console.log('[PhoneChess] connect', wsUrl);
    setWsStatus(t('status.connecting'));
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
      if (pingInterval) clearInterval(pingInterval);
      sendPingProbe();
      pingInterval = setInterval(sendPingProbe, 3000);
    };

    ws.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'queue_counts') {
          if (reconnectTimer) {
            clearInterval(reconnectTimer);
            reconnectTimer = null;
          }
          renderLobbyButtons(msg.counts);
          lastTournamentWaiting = msg.tournament_waiting || { swiss: {}, ko: {} };
          renderTournamentWaiting(lastTournamentWaiting);
          setWsStatus(t('status.connected'), 'connected');
          loadProfile();
          if (pendingStartInviteKey && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'open_private_link', invite_key: pendingStartInviteKey }));
            pendingStartInviteKey = null;
          }
          if (currentGameId && ws && ws.readyState === WebSocket.OPEN) {
            requestGameStateSync(0);
          }
        } else if (msg.type === 'matched') {
          currentQueue = null;
          enterGame(msg);
        } else if (msg.type === 'game_state') {
          console.log('[PhoneChess] WS game_state received');
          applyGameState(msg);
        } else if (msg.type === 'game_update') {
          applyGameState(msg);
        } else if (msg.type === 'draw_offer_state') {
          drawOfferBy = msg.draw_offer_by || null;
          drawOfferColor = msg.draw_offer_color || null;
          drawOfferPly = msg.draw_offer_ply != null ? msg.draw_offer_ply : null;
          updateDrawButton();
          updateClaimDrawButton();
          updateGameAlert();
        } else if (msg.type === 'private_invite_created') {
          const link = msg.invite_link || '';
          const text = t('lobby.private_share_text', { link: '', tc: msg.time_control || '' })
            .replace(/\s+/g, ' ')
            .replace(/\s+([:;,.!?])/g, '$1')
            .trim();
          if (ws && ws.readyState === WebSocket.OPEN && msg.invite_key) {
            ws.send(JSON.stringify({ type: 'open_private_link', invite_key: msg.invite_key }));
          }
          try {
            const share = 'https://t.me/share/url?url=' + encodeURIComponent(link) + '&text=' + encodeURIComponent(text);
            if (window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.openTelegramLink === 'function') {
              window.Telegram.WebApp.openTelegramLink(share);
            }
          } catch (e) {}
        } else if (msg.type === 'private_invite_waiting') {
          currentQueue = null;
          showScreen('lobby-screen');
          showPrivateWaitingPanel({
            invite_key: msg.invite_key,
            time_control: msg.time_control,
            role: msg.role,
            has_opponent: msg.has_opponent
          });
          setWsStatus(t('lobby.private_waiting'));
        } else if (msg.type === 'private_invite_pending') {
          showScreen('lobby-screen');
          showPrivateWaitingPanel({ role: 'creator', has_opponent: false });
          setWsStatus(t('lobby.private_waiting'));
        } else if (msg.type === 'private_invite_invalid') {
          hidePrivateWaitingPanel();
          setWsStatus(t('lobby.private_invalid'), 'error');
        } else if (msg.type === 'private_invite_taken') {
          hidePrivateWaitingPanel();
          setWsStatus(t('lobby.private_taken'), 'error');
        } else if (msg.type === 'private_game_history') {
          hidePrivateWaitingPanel();
          enterReplayMode(msg);
        } else if (msg.type === 'rematch_offer_available') {
          rematchAvailableGameId = msg.game_id || currentGameId;
          if (currentGameId && rematchAvailableGameId === currentGameId) showResultModal();
        } else if (msg.type === 'rematch_vote_update') {
          if (msg.ready_count === 1) {
            setWsStatus(t('result.rematch_waiting'), 'connected');
          }
        } else if (msg.type === 'tournament_finished') {
          setWsStatus('Турнир завершён', 'connected');
        } else if (msg.type === 'tournament_waiting_ack') {
          setWsStatus('Вы в очереди турнира', 'connected');
        } else if (msg.type === 'opponent_connection') {
          if (msg.status === 'disconnected') {
            opponentDisconnected = true;
            opponentDisconnectGraceSeconds = msg.grace_seconds || 0;
            if (opponentDisconnectDebounceTimer) clearTimeout(opponentDisconnectDebounceTimer);
            opponentDisconnectDebounceTimer = setTimeout(function () {
              if (opponentDisconnected) {
                opponentDisconnectedVisible = true;
                updateGameAlert();
              }
            }, 700);
          } else if (msg.status === 'reconnected') {
            opponentDisconnected = false;
            opponentDisconnectedVisible = false;
            opponentDisconnectGraceSeconds = 0;
            if (opponentDisconnectDebounceTimer) {
              clearTimeout(opponentDisconnectDebounceTimer);
              opponentDisconnectDebounceTimer = null;
            }
          }
          updateGameAlert();
        } else if (msg.type === 'pong') {
          if (msg.client_ts != null) {
            const rtt = Date.now() - Number(msg.client_ts);
            if (Number.isFinite(rtt) && rtt >= 0) {
              pingMs = Math.round(rtt);
              updatePingIndicator();
            }
          }
        }
      } catch (e) {
        console.warn('ws message parse', e);
      }
    };

    ws.onclose = function (ev) {
      console.log('[PhoneChess] WS onclose', ev.code, ev.reason || '');
      ws = null;
      pingMs = null;
      updatePingIndicator();
      if (pingInterval) {
        clearInterval(pingInterval);
        pingInterval = null;
      }
      if (ev.code === 4000) {
        setWsStatus(t('status.reconnecting'), '');
        if (reconnectTimer) return;
        reconnectTimer = setInterval(function () {
          connect();
        }, 1000);
        return;
      }
      if (ev.code === 4009) {
        setWsStatus(t('login.second_session_denied'), 'error');
        return;
      }
      var closeMsg = t('status.disconnected_code', { code: ev.code, reasonPart: ev.reason ? ' — ' + ev.reason : '' });
      setWsStatus(closeMsg, 'error');
      if (reconnectTimer) return;
      if (ev.code === 4001 || ev.code === 4003) return;
      reconnectTimer = setInterval(function () {
        connect();
      }, 3000);
    };

    ws.onerror = function (e) {
      console.warn('[PhoneChess] WS onerror', e);
      setWsStatus(t('status.ws_error'), 'error');
    };
  }

  btnBackGame.addEventListener('click', function () {
    goToLobbyFromGame();
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
        btnResign.textContent = t('game.resign');
        btnResign.classList.remove('resign-confirm');
        ws.send(JSON.stringify({ type: 'resign', game_id: currentGameId }));
      } else {
        resignConfirming = true;
        btnResign.textContent = t('game.resign_confirm');
        btnResign.classList.add('resign-confirm');
        resignConfirmTimeout = setTimeout(function () {
          resignConfirming = false;
          btnResign.textContent = t('game.resign');
          btnResign.classList.remove('resign-confirm');
          resignConfirmTimeout = null;
        }, 3000);
      }
    });
  }
  if (btnDraw) {
    btnDraw.addEventListener('click', function () {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (!currentGameId || gameResult) return;
      const ourCode = myColor === 'white' ? 'white' : 'black';
      if (drawOfferBy && drawOfferColor === ourCode) return;
      if (drawOfferBy && drawOfferColor !== ourCode) {
        ws.send(JSON.stringify({ type: 'respond_draw', game_id: currentGameId, action: 'accept' }));
        return;
      }
      ws.send(JSON.stringify({ type: 'offer_draw', game_id: currentGameId }));
    });
  }
  if (btnPrivateGame) {
    btnPrivateGame.addEventListener('click', function () {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      openPrivateTimeModal();
    });
  }
  if (btnBotGame) {
    btnBotGame.addEventListener('click', function () {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: 'start_bot_game', time_control: '3+0' }));
    });
  }
  if (btnPrivateTimeClose) {
    btnPrivateTimeClose.addEventListener('click', closePrivateTimeModal);
  }
  if (btnProfile) btnProfile.addEventListener('click', function () { openProfileModal(); });
  if (btnLogin) btnLogin.addEventListener('click', function () { openProfileModal(); });
  if (btnLoginSubmit) btnLoginSubmit.addEventListener('click', function () { submitLoginName(); });
  if (btnProfileClose) btnProfileClose.addEventListener('click', function () { closeProfileModal(); });
  if (privateTimeModalEl) {
    privateTimeModalEl.addEventListener('click', function (e) {
      if (e.target === privateTimeModalEl) closePrivateTimeModal();
    });
  }
  if (profileModalEl) {
    profileModalEl.addEventListener('click', function (e) {
      if (e.target === profileModalEl) closeProfileModal();
    });
  }
  if (btnClaimDraw) {
    btnClaimDraw.addEventListener('click', function () {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (!currentGameId || gameResult) return;
      const claimType = canClaimDrawByRules();
      if (!claimType) return;
      ws.send(JSON.stringify({ type: 'claim_draw', game_id: currentGameId, claim_type: claimType }));
    });
  }
  if (btnResultLobby) {
    btnResultLobby.addEventListener('click', function () {
      goToLobbyFromGame();
    });
  }
  if (btnResultAnalysis) {
    btnResultAnalysis.addEventListener('click', function () {
      hideResultModal();
      if (analysisPanelEl) analysisPanelEl.classList.add('active');
      if (!analysisEnabled) {
        analysisEnabled = true;
        if (btnAnalysisToggle) btnAnalysisToggle.textContent = t('analysis.stop');
      }
      scheduleAnalysis();
    });
  }
  if (btnResultRematch) {
    btnResultRematch.addEventListener('click', function () {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const gid = rematchAvailableGameId || currentGameId;
      if (!gid) return;
      ws.send(JSON.stringify({ type: 'rematch_request', game_id: gid }));
    });
  }
  if (btnReplayFirst) btnReplayFirst.addEventListener('click', function () { setReplayIndex(0); });
  if (btnReplayPrev) btnReplayPrev.addEventListener('click', function () { setReplayIndex(replayIndex - 1); });
  if (btnReplayNext) btnReplayNext.addEventListener('click', function () { setReplayIndex(replayIndex + 1); });
  if (btnReplayLast) btnReplayLast.addEventListener('click', function () { setReplayIndex(replayFens.length - 1); });
  if (btnAnalysisToggle) {
    btnAnalysisToggle.addEventListener('click', function () {
      analysisEnabled = !analysisEnabled;
      btnAnalysisToggle.textContent = analysisEnabled ? t('analysis.stop') : t('analysis.start');
      if (!analysisEnabled) {
        stopAnalysis();
      } else {
        scheduleAnalysis();
      }
    });
  }
  if (promotionPickerEl) {
    promotionPickerEl.addEventListener('click', function (e) {
      if (e.target === promotionPickerEl) {
        hidePromotionPicker();
        return;
      }
      const choice = e.target && e.target.closest ? e.target.closest('.promotion-choice') : null;
      if (!choice || !pendingPromotionChoice) return;
      const promotion = choice.dataset.promotion || 'q';
      const data = pendingPromotionChoice;
      hidePromotionPicker();
      submitMove(data.from, data.to, promotion, data.isPremove);
    });
  }

  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) requestGameStateSync(0);
  });
  window.addEventListener('focus', function () {
    requestGameStateSync(0);
  });

  async function initApp() {
    myTelegramId = resolveTelegramId();
    await loadI18n();
    document.documentElement.lang = currentLang;
    applyStaticTexts();
    renderLobbyButtons({});
    renderTournamentWaiting(lastTournamentWaiting);
    await loadBuildInfo();
    await loadProfile();
    const sp = getStartParam();
    if (sp && sp.indexOf('private_') === 0) pendingStartInviteKey = sp.slice('private_'.length);
    connect();
  }

  initApp();
})();
