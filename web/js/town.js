/* Nexus HQ Agent Town — company office: gate, guards, cabins, reel-style walk-in */
(() => {
  const canvas = document.getElementById('town-canvas');
  const stage = document.getElementById('town-stage');
  if (!canvas || !stage) return;

  const ctx = canvas.getContext('2d');
  const liveEl = document.getElementById('town-live-status');

  // Full campus fills a 16:9 floor — matches wide monitors, no tiny island
  const W = 960;
  const H = 540;
  // Canvas integer scale. Text is painted in SCREEN pixels (not 4–6px world fonts)
  // so names stay sharp and readable at any zoom.
  let FIT = 1;
  const TEXT_FACE = '"Segoe UI", Tahoma, system-ui, sans-serif';

  /** Sharp HUD text in real screen pixels (avoids pixelated blur / invisible 4px fonts) */
  function paintText(text, wx, wy, opts = {}) {
    if (!text) return 0;
    const {
      color = '#ffffff',
      align = 'center',
      baseline = 'alphabetic',
      px = 13,
      stroke = '#000000',
      strokeW = 3,
      bold = true,
    } = opts;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = true;
    const x = Math.round(wx * FIT);
    const y = Math.round(wy * FIT);
    // Keep a readable minimum on the actual canvas buffer
    const fontPx = Math.max(12, Math.round(px + Math.max(0, FIT - 1)));
    ctx.font = `${bold ? '700' : '600'} ${fontPx}px ${TEXT_FACE}`;
    ctx.textAlign = align;
    ctx.textBaseline = baseline;
    ctx.lineJoin = 'round';
    ctx.miterLimit = 2;
    ctx.lineWidth = Math.max(2, strokeW + (FIT > 2 ? 1 : 0));
    ctx.strokeStyle = stroke;
    ctx.strokeText(text, x, y);
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
    const w = ctx.measureText(text).width;
    ctx.restore();
    ctx.imageSmoothingEnabled = false;
    return w / FIT; // world-ish width for layout helpers
  }

  function measureScreenText(text, px = 13, bold = true) {
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const fontPx = Math.max(12, Math.round(px + Math.max(0, FIT - 1)));
    ctx.font = `${bold ? '700' : '600'} ${fontPx}px ${TEXT_FACE}`;
    const w = ctx.measureText(text || '').width;
    ctx.restore();
    return w;
  }

  function paintNameplate(wx, wy, title, subtitle, accent) {
    // Compact — avoid stacking text over cabin plaques
    const namePx = 12;
    const subPx = 10;
    const showSub = !!(subtitle && subtitle.length);
    const padX = 8;
    const tw = Math.max(
      measureScreenText(title, namePx),
      showSub ? measureScreenText(subtitle, subPx, false) : 0,
    ) + padX * 2;
    const th = showSub ? 28 : 18;
    const x = Math.round(wx * FIT);
    const y = Math.round(wy * FIT);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.fillStyle = 'rgba(0,0,0,0.88)';
    ctx.strokeStyle = accent || '#22d3ee';
    ctx.lineWidth = 1.5;
    const rx = x - tw / 2;
    const ry = y - (showSub ? 12 : 10);
    roundRect(rx, ry, tw, th, 4);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    ctx.imageSmoothingEnabled = false;
    paintText(title, wx, wy, { px: namePx, color: '#ffffff', strokeW: 2.5 });
    if (showSub) {
      paintText(subtitle, wx, wy + 11 / Math.max(FIT, 1), {
        px: subPx,
        color: accent || '#fbbf24',
        bold: false,
        strokeW: 2,
      });
    }
  }

  // Work cabins — center campus with breathing room (not cramped)
  const CABINS = {
    jarvis: {
      x: 360, y: 56, w: 200, h: 130, door: 's', label: 'BOSS', accent: '#fbbf24', boss: true,
      room: 'MD SUITE', job: 'Managing Director', purpose: 'Commands & briefs',
      floorA: '#2a1810', floorB: '#1a1008', wall: '#92400e', doorColor: '#fbbf24', gate: 'gold',
    },
    hunter: {
      x: 160, y: 64, w: 170, h: 118, door: 's', label: 'KEYS', accent: '#f59e0b',
      room: 'KEYS LAB', job: 'API Scout', purpose: 'Find & test keys',
      floorA: '#2a1a08', floorB: '#1c1206', wall: '#b45309', doorColor: '#f59e0b', gate: 'amber',
    },
    mira: {
      x: 590, y: 64, w: 170, h: 118, door: 's', label: 'STUDIO', accent: '#a78bfa',
      room: 'VIDEO STUDIO', job: 'Creative Director', purpose: 'Shorts & clips',
      floorA: '#1e1030', floorB: '#140a22', wall: '#7c3aed', doorColor: '#a78bfa', gate: 'violet',
    },
    youtube: {
      x: 160, y: 210, w: 140, h: 100, door: 'n', label: 'TUBE', accent: '#ef4444',
      room: 'YT DESK', job: 'Media Runner', purpose: 'Upload & channel',
      floorA: '#2a1010', floorB: '#1a0808', wall: '#dc2626', doorColor: '#ef4444', gate: 'red',
    },
    weather: {
      x: 320, y: 210, w: 140, h: 100, door: 'n', label: 'SKY', accent: '#38bdf8',
      room: 'SKY DESK', job: 'Weather Analyst', purpose: 'Forecasts',
      floorA: '#0c1e2e', floorB: '#08141e', wall: '#0284c7', doorColor: '#38bdf8', gate: 'cyan',
    },
    mail: {
      x: 480, y: 210, w: 140, h: 100, door: 'n', label: 'INBOX', accent: '#f472b6',
      room: 'COMMS', job: 'Communications', purpose: 'Mail & replies',
      floorA: '#2a1020', floorB: '#1a0814', wall: '#db2777', doorColor: '#f472b6', gate: 'pink',
    },
    calendar: {
      x: 640, y: 210, w: 140, h: 100, door: 'n', label: 'CAL', accent: '#4ade80',
      room: 'SCHEDULE', job: 'Scheduler', purpose: 'Meetings & time',
      floorA: '#0e2214', floorB: '#081610', wall: '#16a34a', doorColor: '#4ade80', gate: 'green',
    },
    briefing: {
      x: 320, y: 340, w: 140, h: 88, door: 'n', label: 'BRIEF', accent: '#eab308',
      room: 'INTEL', job: 'Briefing Officer', purpose: 'Daily intel',
      floorA: '#221a08', floorB: '#161208', wall: '#ca8a04', doorColor: '#eab308', gate: 'yellow',
    },
    waiter: {
      x: 490, y: 350, w: 120, h: 64, door: 's', label: 'PANTRY', accent: '#e7e5e4', pantry: true,
      room: 'PANTRY', job: 'Office Waiter', purpose: 'Lunch · bottles',
      floorA: '#1c1917', floorB: '#292524', wall: '#a8a29e', doorColor: '#a8a29e', gate: 'steel',
    },
  };

  // Entertainment wings — BIG corner rooms filling the empty space
  const ZONES = {
    cafe: {
      x: 12, y: 24, w: 130, h: 160, accent: '#fb923c', title: 'CAFE',
      sub: 'Coffee · snacks', kind: 'cafe',
    },
    arcade: {
      x: 818, y: 24, w: 130, h: 160, accent: '#22d3ee', title: 'ARCADE',
      sub: 'Games · high score', kind: 'arcade',
    },
    music: {
      x: 12, y: 200, w: 130, h: 120, accent: '#f472b6', title: 'MUSIC',
      sub: 'Beats · karaoke', kind: 'music',
    },
    library: {
      x: 818, y: 200, w: 130, h: 120, accent: '#94a3b8', title: 'LIBRARY',
      sub: 'Quiet · research', kind: 'library',
    },
    lounge: {
      x: 12, y: 340, w: 130, h: 130, accent: '#a78bfa', title: 'LOUNGE',
      sub: 'Sofas · chill', kind: 'lounge',
    },
    gym: {
      x: 818, y: 340, w: 130, h: 130, accent: '#4ade80', title: 'GYM',
      sub: 'Stretch · reset', kind: 'gym',
    },
    cinema: {
      x: 160, y: 440, w: 140, h: 70, accent: '#f43f5e', title: 'CINEMA',
      sub: 'Watch breaks', kind: 'cinema',
    },
    garden: {
      x: 640, y: 440, w: 140, h: 70, accent: '#86efac', title: 'GARDEN',
      sub: 'Fresh air', kind: 'garden',
    },
  };

  /** Desk + chair layout inside a cabin — room for 3 big monitors */
  function workstation(c) {
    if (c.pantry) {
      return {
        deskX: c.x + 10, deskY: c.y + 14, deskW: 50, deskH: 8,
        chairX: c.x + 28, chairY: c.y + 22,
        sitX: c.x + 28, sitY: c.y + 24,
        face: 3, phoneX: c.x + 55, phoneY: c.y + 14, monY: c.y + 8,
      };
    }
    // Leave space under nameplate for triple screens
    if (c.door === 's') {
      const boss = !!c.boss;
      return {
        deskX: c.x + 14, deskY: c.y + (boss ? 54 : 42), deskW: boss ? 78 : 72, deskH: 12,
        chairX: c.x + (boss ? 48 : 44), chairY: c.y + (boss ? 70 : 58),
        sitX: c.x + (boss ? 48 : 44), sitY: c.y + (boss ? 74 : 62),
        face: 3,
        phoneX: c.x + (boss ? 90 : 82), phoneY: c.y + (boss ? 56 : 44),
        monY: c.y + (boss ? 32 : 20),
      };
    }
    return {
      deskX: c.x + 14, deskY: c.y + c.h - 36, deskW: 72, deskH: 12,
      chairX: c.x + 44, chairY: c.y + c.h - 54,
      sitX: c.x + 44, sitY: c.y + c.h - 50,
      face: 0,
      phoneX: c.x + 82, phoneY: c.y + c.h - 34,
      monY: c.y + c.h - 58,
    };
  }

  // Entrance zone (bottom center)
  const GATE = { x: 420, y: 490, w: 120, h: 20 };
  const LOBBY = { x: 390, y: 458, w: 180, h: 28 };
  const OUTSIDE = { x: 470, y: 520 };

  // Break destinations = entertainment wings (fill campus life)
  const ROAM = Object.values(ZONES).map((z) => ({
    x: z.x + z.w / 2 - 8,
    y: z.y + z.h / 2,
    label: z.title,
    kind: z.kind,
  }));
  const BREAK_LINES = {
    cafe: ['Coffee run.', 'Latte break.', 'Grabbing a bite.'],
    arcade: ['One round.', 'Beating high score.', 'Arcade time.'],
    lounge: ['Sofa chill.', 'Quick nap stretch.', 'Lounge vibe.'],
    gym: ['Stretching.', 'Reset body.', 'Quick workout.'],
    music: ['Song break.', 'Karaoke energy.', 'Beats on.'],
    library: ['Quiet read.', 'Research pause.', 'Library quiet.'],
    cinema: ['Trailer break.', 'Watching a clip.', 'Cinema chill.'],
    garden: ['Fresh air.', 'Garden walk.', 'Reset outside.'],
  };

  // Full human identities (like real employees — not floating labels)
  const PEOPLE = {
    jarvis: {
      fullName: 'Adrian Cole', first: 'Adrian', role: 'Boss · MD',
      title: 'Managing Director', hair: 'short', body: 'tall', suit: true,
      skin: '#e8b898', hairC: '#0f172a', shirt: '#f8fafc', pants: '#0f172a',
      coat: '#020617', tie: '#b91c1c', shoes: '#000', accent: '#fbbf24', eye: '#1e3a5f',
    },
    hunter: {
      fullName: 'Kai Morales', first: 'Kai', role: 'API Scout',
      title: 'Keys Specialist', hair: 'messy', body: 'med',
      skin: '#c9956c', hairC: '#3b2110', shirt: '#d97706', pants: '#5c3a10',
      shoes: '#1c1917', accent: '#fbbf24', eye: '#451a03',
    },
    mira: {
      fullName: 'Mira Chen', first: 'Mira', role: 'Creative Director',
      title: 'Video Producer', hair: 'long', body: 'med',
      skin: '#f0c4b0', hairC: '#4c1d95', shirt: '#8b5cf6', pants: '#3b0764',
      shoes: '#2e1065', accent: '#c4b5fd', eye: '#5b21b6',
    },
    youtube: {
      fullName: 'Diego Santos', first: 'Diego', role: 'Media Runner',
      title: 'YouTube Desk', hair: 'fade', body: 'tall',
      skin: '#d4a074', hairC: '#1c1917', shirt: '#dc2626', pants: '#450a0a',
      shoes: '#0f172a', accent: '#fca5a5', eye: '#7f1d1d',
    },
    weather: {
      fullName: 'Nora Blake', first: 'Nora', role: 'Weather Analyst',
      title: 'Climate Desk', hair: 'bob', body: 'med',
      skin: '#f5d0b8', hairC: '#0c4a6e', shirt: '#0ea5e9', pants: '#075985',
      shoes: '#0f172a', accent: '#7dd3fc', eye: '#0369a1',
    },
    mail: {
      fullName: 'Priya Kapoor', first: 'Priya', role: 'Communications',
      title: 'Inbox Lead', hair: 'long', body: 'med',
      skin: '#e8b890', hairC: '#831843', shirt: '#db2777', pants: '#9d174d',
      shoes: '#500724', accent: '#f9a8d4', eye: '#9d174d',
    },
    calendar: {
      fullName: 'Ethan Brooks', first: 'Ethan', role: 'Scheduler',
      title: 'Meetings Lead', hair: 'short', body: 'tall',
      skin: '#f0d0b0', hairC: '#14532d', shirt: '#16a34a', pants: '#14532d',
      shoes: '#052e16', accent: '#86efac', eye: '#166534',
    },
    briefing: {
      fullName: 'Sam Okonkwo', first: 'Sam', role: 'Briefing Officer',
      title: 'Morning Intel', hair: 'short', body: 'tall',
      skin: '#8d5524', hairC: '#1c1917', shirt: '#ca8a04', pants: '#713f12',
      shoes: '#422006', accent: '#fde047', eye: '#292524',
    },
    waiter: {
      fullName: 'Ravi Mehta', first: 'Ravi', role: 'Office Waiter',
      title: 'Pantry Service', hair: 'short', body: 'med', waiter: true,
      skin: '#d4a574', hairC: '#1c1917', shirt: '#fafaf9', pants: '#44403c',
      apron: '#292524', shoes: '#0f172a', accent: '#a8a29e', eye: '#292524',
    },
    guard1: {
      fullName: 'Omar Reed', first: 'Omar', role: 'Security',
      title: 'Gate Guard', hair: 'short', body: 'tall',
      skin: '#c4a574', hairC: '#0f172a', shirt: '#334155', pants: '#0f172a',
      shoes: '#020617', accent: '#94a3b8', eye: '#1e293b',
    },
    guard2: {
      fullName: 'Lena Cho', first: 'Lena', role: 'Security',
      title: 'Gate Guard', hair: 'bob', body: 'med',
      skin: '#e8c4a8', hairC: '#111827', shirt: '#1e293b', pants: '#020617',
      shoes: '#000', accent: '#64748b', eye: '#0f172a',
    },
  };

  function makeChar(id, deskKey, opts = {}) {
    const p = PEOPLE[id] || PEOPLE.jarvis;
    return {
      id,
      name: p.fullName,
      first: p.first,
      role: p.role,
      title: p.title,
      look: p,
      deskKey,
      x: opts.x ?? OUTSIDE.x,
      y: opts.y ?? OUTSIDE.y,
      tx: opts.x ?? OUTSIDE.x,
      ty: opts.y ?? OUTSIDE.y,
      dir: 3,
      frame: 0,
      frameT: 0,
      mode: 'idle',
      status: opts.status || 'offsite',
      activity: '',
      bubble: '',
      bubbleT: 0,
      workAnim: 0,
      visible: !!opts.visible,
      path: [],
      nextRoam: 90 + Math.random() * 120,
      _then: null,
      isGuard: !!opts.isGuard,
      isWaiter: !!p.waiter,
      _onArrive: null,
      carrying: null, // 'tray' | 'bottles' | null
    };
  }

  const agents = {
    jarvis: makeChar('jarvis', 'jarvis'),
    hunter: makeChar('hunter', 'hunter'),
    mira: makeChar('mira', 'mira'),
    youtube: makeChar('youtube', 'youtube'),
    weather: makeChar('weather', 'weather'),
    mail: makeChar('mail', 'mail'),
    calendar: makeChar('calendar', 'calendar'),
    briefing: makeChar('briefing', 'briefing'),
    waiter: makeChar('waiter', 'waiter'),
  };

  const guards = {
    guard1: makeChar('guard1', null, {
      x: GATE.x - 18, y: GATE.y + 6, visible: true, status: 'online', isGuard: true,
    }),
    guard2: makeChar('guard2', null, {
      x: GATE.x + GATE.w + 6, y: GATE.y + 6, visible: true, status: 'online', isGuard: true,
    }),
  };
  guards.guard1.deskKey = null;
  guards.guard2.deskKey = null;

  // World state
  const world = {
    dayStarted: false,
    gateOpen: 0, // 0..1
    doorOpen: {}, // cabinId -> 0..1
    bootPhase: 'waiting', // waiting | guards | gate | enter | done
    bootMsg: 'NEXUS HQ · sealed — activate Jarvis to open the day',
    intercom: '',
    intercomT: 0,
  };
  Object.keys(CABINS).forEach((k) => { world.doorOpen[k] = 0; });

  const ENTRY_ORDER = ['jarvis', 'hunter', 'mira', 'youtube', 'weather', 'mail', 'calendar', 'briefing', 'waiter'];

  const IDLE_LINES = {
    jarvis: ['Call them to my cabin.', 'Intercom clear.', 'HQ online.'],
    hunter: ['Keys cabin warm.', 'Name a provider.'],
    mira: ['Studio warm.', 'Ready for a brief.'],
    youtube: ['Tube standing by.'],
    weather: ['Skies tracked.'],
    mail: ['Inbox clear.'],
    calendar: ['Schedule open.'],
    briefing: ['Brief stacked.'],
    waiter: ['Pantry ready.', 'Call me on intercom.', 'Lunch trays set.'],
    guard1: ['Gate secure.', 'IDs ready.'],
    guard2: ['All clear.', 'Welcome to Nexus.'],
  };

  // ── Drawing helpers ──
  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawMonitor(mx, my, mw, mh, lit, hue) {
    // bezel
    ctx.fillStyle = '#0b1220';
    ctx.fillRect(mx - 2, my - 2, mw + 4, mh + 5);
    // stand
    ctx.fillStyle = '#334155';
    ctx.fillRect(mx + mw / 2 - 2, my + mh + 1, 4, 3);
    ctx.fillRect(mx + mw / 2 - 6, my + mh + 4, 12, 2);
    // screen
    if (lit) {
      const t = performance.now() / 80;
      ctx.fillStyle = hue || '#022c22';
      ctx.fillRect(mx, my, mw, mh);
      // animated UI lines
      ctx.fillStyle = '#22d3ee';
      for (let i = 0; i < 5; i++) {
        const w = 4 + ((Math.floor(t) + i * 3) % (mw - 4));
        ctx.globalAlpha = 0.45 + (i % 2) * 0.35;
        ctx.fillRect(mx + 2, my + 2 + i * 3, w, 1.5);
      }
      // window chrome
      ctx.globalAlpha = 0.9;
      ctx.fillStyle = '#67e8f9';
      ctx.fillRect(mx + 1, my + 1, mw - 2, 2);
      ctx.globalAlpha = 1;
      // glow
      ctx.fillStyle = 'rgba(34,211,238,0.12)';
      ctx.fillRect(mx - 1, my - 1, mw + 2, mh + 2);
    } else {
      ctx.fillStyle = '#020617';
      ctx.fillRect(mx, my, mw, mh);
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(mx + 3, my + mh / 2 - 1, mw - 6, 2);
    }
  }

  function drawAutoGate(c, open) {
    const doorW = c.boss ? 34 : 24;
    const doorX = c.x + (c.w - doorW) / 2;
    const slide = open * (c.boss ? 18 : 14);
    const col = c.doorColor || c.accent || '#38bdf8';
    const y = c.door === 's' ? c.y + c.h - 7 : c.y - 2;
    // track
    ctx.fillStyle = '#020617';
    ctx.fillRect(doorX - 14, y, doorW + 28, 8);
    ctx.fillStyle = col + '44';
    ctx.fillRect(doorX, y + 1, doorW, 6);
    // sliding panels (unique color per cabin)
    ctx.fillStyle = col;
    ctx.fillRect(doorX - 12 + slide, y, 12, 7);
    ctx.fillRect(doorX + doorW - slide, y, 12, 7);
    // glass strip
    ctx.fillStyle = '#e0f2fe88';
    ctx.fillRect(doorX - 10 + slide, y + 2, 8, 3);
    ctx.fillRect(doorX + doorW + 2 - slide, y + 2, 8, 3);
    // sensor LED
    ctx.fillStyle = open > 0.55 ? '#4ade80' : '#ef4444';
    ctx.fillRect(doorX + doorW / 2 - 2, y - 3, 4, 3);
    // AUTO label tick
    if (c.boss) {
      ctx.fillStyle = '#fbbf24';
      ctx.fillRect(doorX - 16, y + 1, 3, 5);
      ctx.fillRect(doorX + doorW + 13, y + 1, 3, 5);
    }
  }

  function drawCabin(id, c) {
    const open = world.doorOpen[id] || 0;
    const ws = workstation(c);
    const agentHere = agents[id];
    const working = !!(agentHere && agentHere.visible && (agentHere.mode === 'work' || agentHere.status === 'working'));
    const lit = working || (agentHere && agentHere.visible && world.dayStarted);
    const person = PEOPLE[id];

    // Pantry
    if (c.pantry) {
      ctx.fillStyle = c.floorA || '#1c1917';
      ctx.fillRect(c.x + 2, c.y + 2, c.w - 4, c.h - 4);
      ctx.strokeStyle = c.wall || '#a8a29e';
      ctx.lineWidth = 2;
      ctx.strokeRect(c.x, c.y, c.w, c.h);
      ctx.fillStyle = '#44403c';
      ctx.fillRect(c.x + 8, c.y + 14, c.w - 16, 10);
      ctx.fillStyle = '#22d3ee';
      ctx.fillRect(c.x + 12, c.y + 10, 4, 6);
      ctx.fillRect(c.x + 20, c.y + 10, 4, 6);
      ctx.fillStyle = '#fbbf24';
      ctx.fillRect(c.x + 30, c.y + 11, 6, 5);
      ctx.fillStyle = '#ef4444';
      ctx.fillRect(c.x + 40, c.y + 10, 4, 6);
      drawAutoGate(c, open);
      paintText('PANTRY', c.x + c.w / 2, c.y + 8, { px: 11, color: '#fafaf9' });
      paintText('Ravi · Waiter', c.x + c.w / 2, c.y + 36, { px: 11, color: '#fbbf24', bold: false });
      return;
    }

    // Floor (unique per cabin)
    ctx.fillStyle = c.floorA || '#152033';
    ctx.fillRect(c.x + 2, c.y + 2, c.w - 4, c.h - 4);
    for (let ty = c.y + 6; ty < c.y + c.h - 8; ty += 8) {
      for (let tx = c.x + 6; tx < c.x + c.w - 8; tx += 8) {
        ctx.fillStyle = ((tx + ty) % 16 === 0) ? (c.floorB || '#162338') : (c.floorA || '#152033');
        ctx.fillRect(tx, ty, 7, 7);
      }
    }

    // Walls — boss gets thick gold double frame
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(c.x, c.y, c.w, c.boss ? 6 : 5);
    ctx.fillRect(c.x, c.y + c.h - (c.boss ? 6 : 5), c.w, c.boss ? 6 : 5);
    ctx.fillRect(c.x, c.y, c.boss ? 6 : 5, c.h);
    ctx.fillRect(c.x + c.w - (c.boss ? 6 : 5), c.y, c.boss ? 6 : 5, c.h);
    ctx.strokeStyle = c.wall || c.accent || '#64748b';
    ctx.lineWidth = c.boss ? 3 : 1.5;
    ctx.strokeRect(c.x + 1, c.y + 1, c.w - 2, c.h - 2);
    if (c.boss) {
      ctx.strokeStyle = '#fde047';
      ctx.lineWidth = 1;
      ctx.strokeRect(c.x + 4, c.y + 4, c.w - 8, c.h - 8);
      // crown stripe
      ctx.fillStyle = '#fbbf24';
      ctx.fillRect(c.x + 10, c.y + 2, c.w - 20, 3);
    }

    drawAutoGate(c, open);

    // Workstation
    const dx = ws.deskX;
    const dy = ws.deskY;
    ctx.fillStyle = c.boss ? '#3f2a14' : '#5c4030';
    ctx.fillRect(dx - 4, dy, ws.deskW + 16, ws.deskH);
    ctx.fillStyle = c.boss ? '#fbbf24' : '#8b6914';
    ctx.fillRect(dx - 4, dy, ws.deskW + 16, 3);
    ctx.fillStyle = '#3f2a1a';
    ctx.fillRect(dx - 4, dy + ws.deskH, ws.deskW + 16, 3);

    const monY = ws.monY;
    const screenH = c.boss ? 24 : 20;
    const screenW = c.boss ? 26 : 22;
    drawMonitor(dx + 0, monY, screenW, screenH, lit, id === 'mira' ? '#1e1b4b' : (c.boss ? '#422006' : '#022c22'));
    drawMonitor(dx + screenW + 2, monY, screenW, screenH, lit, id === 'hunter' ? '#422006' : '#021a1a');
    drawMonitor(dx + (screenW + 2) * 2, monY, screenW, screenH, lit, '#0c1929');

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(dx + 12, dy + 3, 36, 8);
    ctx.fillStyle = '#475569';
    for (let row = 0; row < 3; row++) {
      for (let k = 0; k < 10; k++) ctx.fillRect(dx + 14 + k * 3, dy + 4 + row * 2, 2, 1.5);
    }
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(dx + 52, dy + 3, 10, 8);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(dx + 54, dy + 4, 5, 6);
    ctx.fillStyle = '#020617';
    ctx.fillRect(ws.phoneX - 2, ws.phoneY, 12, 10);
    ctx.fillStyle = c.accent;
    ctx.fillRect(ws.phoneX, ws.phoneY + 2, 8, 3);

    const cx = ws.chairX;
    const cy = ws.chairY;
    ctx.fillStyle = c.boss ? '#292524' : '#1e293b';
    ctx.fillRect(cx - 2, cy - 8, 16, 12);
    ctx.fillStyle = '#334155';
    ctx.fillRect(cx, cy + 2, 12, 6);
    ctx.fillStyle = '#64748b';
    ctx.fillRect(cx + 5, cy + 8, 2, 5);
    ctx.fillRect(cx, cy + 12, 12, 2);

    // Identity plate — room + person only (job lives on Crew Board — less mess)
    const plateH = c.boss ? 26 : 22;
    ctx.fillStyle = c.boss ? '#1c1408' : '#0b1220';
    ctx.fillRect(c.x + 5, c.y + 5, c.w - 10, plateH);
    ctx.strokeStyle = c.accent;
    ctx.lineWidth = c.boss ? 2 : 1.5;
    ctx.strokeRect(c.x + 5, c.y + 5, c.w - 10, plateH);
    const title = c.boss ? '★ BOSS CABIN' : (c.room || c.label);
    paintText(title, c.x + c.w / 2, c.y + 14, { px: c.boss ? 12 : 11, color: c.accent, strokeW: 2.5 });
    if (person) {
      const who = c.boss ? 'Adrian · MD' : person.first;
      paintText(who, c.x + c.w / 2, c.y + 24, { px: 10, color: '#f8fafc', bold: false, strokeW: 2 });
    }
    // Tiny live status only when working (no purpose spam)
    if (working && agentHere && agentHere.activity) {
      paintText(`▶ ${String(agentHere.activity).slice(0, 18)}`, c.x + c.w / 2, c.y + plateH + 11, {
        px: 10,
        color: '#fde047',
        strokeW: 2,
      });
    }
  }

  function drawZone(z) {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(z.x, z.y, z.w, z.h);
    ctx.strokeStyle = z.accent;
    ctx.lineWidth = 2;
    ctx.strokeRect(z.x + 1, z.y + 1, z.w - 2, z.h - 2);
    // soft fill
    ctx.fillStyle = z.accent + '22';
    ctx.fillRect(z.x + 4, z.y + 4, z.w - 8, z.h - 8);

    if (z.kind === 'cafe') {
      ctx.fillStyle = '#78350f';
      ctx.fillRect(z.x + 10, z.y + 40, z.w - 20, 14);
      ctx.fillStyle = '#fbbf24';
      for (let i = 0; i < 3; i++) ctx.fillRect(z.x + 16 + i * 22, z.y + 28, 10, 12);
      ctx.fillStyle = '#86efac';
      ctx.fillRect(z.x + 14, z.y + 70, 18, 18);
      ctx.fillRect(z.x + 50, z.y + 78, 18, 18);
    } else if (z.kind === 'arcade') {
      for (let i = 0; i < 3; i++) {
        ctx.fillStyle = '#020617';
        ctx.fillRect(z.x + 12 + i * 26, z.y + 36, 20, 40);
        ctx.fillStyle = i === 1 ? '#22d3ee' : '#a78bfa';
        ctx.fillRect(z.x + 14 + i * 26, z.y + 40, 16, 14);
        ctx.fillStyle = '#f43f5e';
        ctx.fillRect(z.x + 18 + i * 26, z.y + 62, 8, 4);
      }
    } else if (z.kind === 'lounge') {
      ctx.fillStyle = '#4c1d95';
      ctx.fillRect(z.x + 12, z.y + 40, 40, 22);
      ctx.fillRect(z.x + 58, z.y + 48, 36, 20);
      ctx.fillStyle = '#c4b5fd';
      ctx.fillRect(z.x + 16, z.y + 36, 32, 6);
      ctx.fillStyle = '#fbbf24';
      ctx.fillRect(z.x + 48, z.y + 70, 14, 10);
    } else if (z.kind === 'gym') {
      ctx.fillStyle = '#14532d';
      ctx.fillRect(z.x + 16, z.y + 50, 50, 8);
      ctx.fillStyle = '#94a3b8';
      ctx.fillRect(z.x + 20, z.y + 44, 8, 20);
      ctx.fillRect(z.x + 54, z.y + 44, 8, 20);
      ctx.fillStyle = '#4ade80';
      ctx.beginPath();
      ctx.arc(z.x + 80, z.y + 60, 12, 0, Math.PI * 2);
      ctx.fill();
    } else if (z.kind === 'music') {
      ctx.fillStyle = '#831843';
      ctx.fillRect(z.x + 20, z.y + 50, 50, 20);
      ctx.fillStyle = '#f9a8d4';
      ctx.fillRect(z.x + 28, z.y + 40, 8, 12);
      ctx.fillRect(z.x + 48, z.y + 36, 8, 16);
      ctx.fillStyle = '#22d3ee';
      ctx.beginPath();
      ctx.arc(z.x + 70, z.y + 70, 10, 0, Math.PI * 2);
      ctx.fill();
    } else if (z.kind === 'library') {
      for (let i = 0; i < 4; i++) {
        ctx.fillStyle = ['#b45309', '#1d4ed8', '#be123c', '#15803d'][i];
        ctx.fillRect(z.x + 18 + i * 24, z.y + 44, 18, 48);
      }
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(z.x + 24, z.y + 100, 70, 8);
    } else if (z.kind === 'cinema') {
      ctx.fillStyle = '#1c1917';
      ctx.fillRect(z.x + 16, z.y + 28, z.w - 32, 28);
      ctx.fillStyle = '#f43f5e';
      ctx.fillRect(z.x + 22, z.y + 32, z.w - 44, 20);
      ctx.fillStyle = '#44403c';
      ctx.fillRect(z.x + 20, z.y + 58, 20, 8);
      ctx.fillRect(z.x + 50, z.y + 58, 20, 8);
      ctx.fillRect(z.x + 80, z.y + 58, 20, 8);
    } else if (z.kind === 'garden') {
      ctx.fillStyle = '#14532d';
      ctx.fillRect(z.x + 10, z.y + 36, z.w - 20, 24);
      ctx.fillStyle = '#4ade80';
      for (let i = 0; i < 5; i++) {
        ctx.beginPath();
        ctx.arc(z.x + 24 + i * 22, z.y + 40, 8, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    paintText(z.title, z.x + z.w / 2, z.y + 18, { px: 13, color: z.accent, strokeW: 2.5 });
    paintText(z.sub, z.x + z.w / 2, z.y + 32, { px: 10, color: '#e2e8f0', bold: false, strokeW: 2 });
  }

  function drawHQ() {
    // Full floor tiles — no empty black voids inside the map
    for (let y = 0; y < H; y += 16) {
      for (let x = 0; x < W; x += 16) {
        const outside = y >= 480;
        ctx.fillStyle = outside
          ? (((x / 16) + (y / 16)) % 2 === 0 ? '#0f172a' : '#0a0e14')
          : (((x / 16) + (y / 16)) % 2 === 0 ? '#243448' : '#1e2c3e');
        ctx.fillRect(x, y, 16, 16);
      }
    }

    ctx.strokeStyle = '#94a3b8';
    ctx.lineWidth = 3;
    ctx.strokeRect(4, 8, W - 8, 470);

    ctx.fillStyle = '#1a2333';
    ctx.fillRect(150, 185, 660, 20);
    ctx.fillRect(300, 320, 360, 16);
    ctx.fillRect(300, 430, 360, 16);

    ctx.fillStyle = '#312e81';
    ctx.fillRect(LOBBY.x, LOBBY.y, LOBBY.w, LOBBY.h);
    ctx.fillStyle = '#4c1d95';
    ctx.fillRect(LOBBY.x + 4, LOBBY.y + 4, LOBBY.w - 8, LOBBY.h - 8);

    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(456, 16, 48, 28);
    paintText('NEXUS', 480, 28, { px: 13, color: '#0f172a', stroke: '#fff', strokeW: 2 });
    paintText('HQ', 480, 40, { px: 12, color: '#0f172a', stroke: '#fff', strokeW: 2 });

    [[170, 195], [780, 195], [340, 328], [620, 328]].forEach(([px, py]) => {
      ctx.fillStyle = '#854d0e';
      ctx.fillRect(px, py, 8, 8);
      ctx.fillStyle = '#16a34a';
      ctx.beginPath();
      ctx.arc(px + 4, py - 2, 7, 0, Math.PI * 2);
      ctx.fill();
    });

    Object.values(ZONES).forEach(drawZone);
    Object.entries(CABINS).forEach(([id, c]) => drawCabin(id, c));

    const gx = GATE.x;
    const gy = GATE.y;
    const gw = GATE.w;
    const open = world.gateOpen;
    ctx.fillStyle = '#475569';
    ctx.fillRect(gx - 6, gy - 4, 6, 22);
    ctx.fillRect(gx + gw, gy - 4, 6, 22);
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(gx - 8, gy - 8, gw + 16, 5);
    const slide = open * (gw / 2 - 2);
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(gx, gy, gw / 2 - slide, 16);
    ctx.fillRect(gx + gw / 2 + slide, gy, gw / 2 - slide, 16);
    ctx.strokeStyle = '#22d3ee';
    ctx.lineWidth = 1;
    ctx.strokeRect(gx, gy, gw / 2 - slide, 16);
    ctx.strokeRect(gx + gw / 2 + slide, gy, gw / 2 - slide, 16);
    paintText(open > 0.8 ? 'OPEN' : 'NEXUS GATE', gx + gw / 2, gy - 12, {
      px: 13,
      color: '#67e8f9',
    });

    ctx.fillStyle = '#1e293b';
    ctx.fillRect(gx - 44, gy - 2, 30, 22);
    ctx.fillRect(gx + gw + 14, gy - 2, 30, 22);
    paintText('OMAR', gx - 29, gy + 12, { px: 11, color: '#e2e8f0' });
    paintText('LENA', gx + gw + 29, gy + 12, { px: 11, color: '#e2e8f0' });
  }

  /** Human-looking RPG agent — face, hair, body, walk (not a sliding icon) */
  function drawChar(a) {
    if (!a.visible) return;
    const p = a.look || PEOPLE[a.id] || PEOPLE.jarvis;
    const walking = a.mode === 'walk';
    const working = a.mode === 'work';
    const bob = walking ? Math.sin(a.frame * Math.PI) * 2.2 : 0;
    const lean = working ? Math.sin(a.workAnim * 9) * 1.0 : 0;
    const tall = p.body === 'tall' ? 1.15 : 1.05;
    const s = (a.isGuard ? 1.1 : 1.35) * tall;
    const x = Math.round(a.x + lean);
    const y = Math.round(a.y + bob);
    const step = walking ? (a.frame % 2 === 0 ? -2.5 : 2.5) : 0;

    ctx.save();
    ctx.translate(x + 8, y + 28);
    ctx.scale(s, s);
    ctx.translate(-8, -28);

    ctx.fillStyle = 'rgba(0,0,0,0.45)';
    ctx.beginPath();
    ctx.ellipse(8, 27, 8, 2.4, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = p.shoes;
    ctx.fillRect(3 + (walking ? step * 0.4 : 0), 24, 5, 3);
    ctx.fillRect(9 - (walking ? step * 0.4 : 0), 24, 5, 3);

    ctx.fillStyle = p.pants;
    ctx.fillRect(4, 18, 4, 7 + step * 0.45);
    ctx.fillRect(9, 18, 4, 7 - step * 0.45);

    // Body — boss pant-coat suit (clear MD look) OR waiter apron OR shirt
    if (p.suit) {
      ctx.fillStyle = p.coat || '#020617';
      ctx.fillRect(1, 9, 15, 12); // long pant-coat
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(2, 18, 13, 3); // coat hem
      ctx.fillStyle = p.shirt || '#fff';
      ctx.fillRect(5, 10, 7, 8);
      ctx.fillStyle = p.tie || '#b91c1c';
      ctx.fillRect(7, 11, 2, 7);
      ctx.fillStyle = '#fbbf24';
      ctx.fillRect(3, 10, 2, 2);
      ctx.fillRect(12, 10, 2, 2);
      // MD badge
      ctx.fillStyle = '#fde047';
      ctx.fillRect(4, 14, 3, 3);
      ctx.fillStyle = '#92400e';
      ctx.fillRect(5, 15, 1, 1);
    } else if (p.waiter) {
      ctx.fillStyle = p.shirt;
      ctx.fillRect(3, 10, 11, 9);
      ctx.fillStyle = p.apron || '#292524';
      ctx.fillRect(4, 12, 9, 8);
      ctx.fillStyle = '#a8a29e';
      ctx.fillRect(7, 13, 3, 2);
    } else {
      ctx.fillStyle = p.shirt;
      ctx.fillRect(3, 10, 11, 9);
      ctx.fillStyle = p.accent;
      ctx.fillRect(7, 10, 3, 2);
    }
    if (a.isGuard) {
      ctx.fillStyle = '#fbbf24';
      ctx.fillRect(6, 13, 5, 2);
    }

    if (working && !p.waiter) {
      ctx.fillStyle = p.suit ? (p.coat || '#020617') : p.shirt;
      ctx.fillRect(0, 11, 3, 5);
      ctx.fillRect(14, 11, 3, 5);
      ctx.fillStyle = p.skin;
      const armY = 14 + Math.sin(a.workAnim * 12) * 1.8;
      ctx.fillRect(14, armY, 5, 3);
      ctx.fillRect(-1, 15, 3, 2);
    } else if (walking || p.waiter) {
      ctx.fillStyle = p.suit ? (p.coat || '#020617') : p.shirt;
      ctx.fillRect(0, 11 + step * 0.35, 3, 6);
      ctx.fillRect(14, 11 - step * 0.35, 3, 6);
      ctx.fillStyle = p.skin;
      ctx.fillRect(0, 16 + step * 0.35, 3, 2);
      ctx.fillRect(14, 16 - step * 0.35, 3, 2);
      // Service tray
      if (p.waiter || a.carrying) {
        ctx.fillStyle = '#a8a29e';
        ctx.fillRect(15, 12, 10, 3);
        ctx.fillStyle = '#22d3ee';
        ctx.fillRect(16, 10, 2, 3); // bottle
        ctx.fillStyle = '#fbbf24';
        ctx.fillRect(20, 11, 3, 2); // cup
        ctx.fillStyle = '#ef4444';
        ctx.fillRect(24, 10, 2, 3);
      }
    } else {
      ctx.fillStyle = p.suit ? (p.coat || '#020617') : p.shirt;
      ctx.fillRect(0, 11, 3, 6);
      ctx.fillRect(14, 11, 3, 6);
      ctx.fillStyle = p.skin;
      ctx.fillRect(0, 16, 3, 2);
      ctx.fillRect(14, 16, 3, 2);
    }

    ctx.fillStyle = p.skin;
    ctx.fillRect(6, 8, 5, 3);
    ctx.fillRect(4, 1, 9, 8);
    ctx.fillRect(3, 4, 2, 3);
    ctx.fillRect(12, 4, 2, 3);

    ctx.fillStyle = p.hairC;
    if (a.dir === 3) {
      ctx.fillRect(3, 0, 11, 9);
    } else {
      ctx.fillRect(3, 0, 11, 4);
      if (p.hair === 'long') {
        ctx.fillRect(2, 3, 3, 9);
        ctx.fillRect(12, 3, 3, 9);
      } else if (p.hair === 'bob') {
        ctx.fillRect(2, 3, 3, 6);
        ctx.fillRect(12, 3, 3, 6);
      } else if (p.hair === 'messy') {
        ctx.fillRect(3, 0, 3, 3);
        ctx.fillRect(8, 0, 2, 2);
        ctx.fillRect(11, 0, 3, 3);
      } else if (p.hair === 'fade') {
        ctx.fillRect(4, 0, 9, 3);
      }
    }

    if (a.dir !== 3) {
      ctx.fillStyle = '#fff';
      if (a.dir === 1) {
        ctx.fillRect(5, 4, 3, 3);
        ctx.fillStyle = p.eye;
        ctx.fillRect(5, 5, 2, 2);
      } else if (a.dir === 2) {
        ctx.fillRect(9, 4, 3, 3);
        ctx.fillStyle = p.eye;
        ctx.fillRect(10, 5, 2, 2);
      } else {
        ctx.fillRect(5, 4, 3, 3);
        ctx.fillRect(9, 4, 3, 3);
        ctx.fillStyle = p.eye;
        ctx.fillRect(6, 5, 2, 2);
        ctx.fillRect(10, 5, 2, 2);
        ctx.fillStyle = '#c2410c';
        ctx.fillRect(7, 8, 3, 1);
      }
    }

    ctx.restore();

    const bx = x + 8;
    const by = y + 40;
    const label = a.id === 'jarvis'
      ? `★ ${a.first || 'Adrian'}`
      : (a.first || (a.name || '').split(' ')[0] || a.id);
    // Quiet desks: nameplate only when walking / working / break (cabin plaque already has name)
    let sub = '';
    if (a.mode === 'walk') sub = 'walking…';
    else if (a.status === 'working' && a.activity) sub = String(a.activity).slice(0, 18);
    else if (a.mode === 'idle' && a._breakTimer) sub = 'on break';
    const accent = (CABINS[a.deskKey] && CABINS[a.deskKey].accent)
      || (a.look && a.look.accent)
      || '#22d3ee';
    if (a.isGuard || sub || a.id === 'jarvis') {
      paintNameplate(bx, by, label, a.isGuard ? '' : sub, accent);
    }
  }

  function drawBubble(a) {
    if (!a.visible || !a.bubble || a.bubbleT <= 0) return;
    const text = a.bubble.length > 42 ? a.bubble.slice(0, 40) + '…' : a.bubble;
    const px = 13;
    const padX = 14;
    const twScreen = Math.min(280 * FIT, Math.max(80, measureScreenText(text, px) + padX * 2));
    const thScreen = 28;
    const tw = twScreen / FIT;
    const th = thScreen / FIT;
    const bx = a.x + 8 - tw / 2;
    const by = a.y - th - 10;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = true;
    const sx = Math.round(bx * FIT);
    const sy = Math.round(by * FIT);
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = 2.5;
    roundRect(sx, sy, twScreen, thScreen, 8);
    ctx.fill();
    ctx.stroke();
    // tail
    ctx.beginPath();
    ctx.moveTo(Math.round((a.x + 5) * FIT), sy + thScreen);
    ctx.lineTo(Math.round((a.x + 8) * FIT), sy + thScreen + 8);
    ctx.lineTo(Math.round((a.x + 11) * FIT), sy + thScreen);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    ctx.imageSmoothingEnabled = false;
    paintText(text, a.x + 8, by + th * 0.62, {
      px,
      color: '#0f172a',
      stroke: '#ffffff',
      strokeW: 2,
    });
  }

  // ── Movement ──
  function setBubble(id, text, secs = 3.5) {
    const a = agents[id] || guards[id];
    if (!a || !text) return;
    a.bubble = String(text).slice(0, 70);
    a.bubbleT = secs;
  }

  function queuePath(a, points, thenMode) {
    a.path = points.map((p) => ({ x: p.x, y: p.y }));
    a._then = thenMode || 'idle';
    if (a.path.length) {
      const n = a.path.shift();
      a.tx = n.x;
      a.ty = n.y;
      a.mode = 'walk';
    }
  }

  function walkTo(a, x, y, thenMode) {
    a.tx = x;
    a.ty = y;
    a.mode = 'walk';
    a._then = thenMode || 'idle';
    a.path = [];
  }

  function cabinDoorPoint(cabin) {
    const doorW = 24;
    const doorX = cabin.x + (cabin.w - doorW) / 2 + doorW / 2;
    if (cabin.door === 's') return { x: doorX - 8, y: cabin.y + cabin.h + 4 };
    return { x: doorX - 8, y: cabin.y - 10 };
  }

  function sitPoint(cabin) {
    const ws = workstation(cabin);
    return { x: ws.sitX, y: ws.sitY, face: ws.face };
  }

  function bossGuestSpot() {
    const c = CABINS.jarvis;
    return { x: c.x + 78, y: c.y + 72 };
  }

  /** Auto cabin gates — open when someone is near / inside, close when empty */
  function updateDoors(dt) {
    Object.entries(CABINS).forEach(([id, c]) => {
      const door = cabinDoorPoint(c);
      let want = 0;
      Object.values(agents).forEach((a) => {
        if (!a.visible) return;
        const nearDoor = (a.x - door.x) ** 2 + (a.y - door.y) ** 2 < 32 * 32;
        const inside = a.x > c.x + 4 && a.x < c.x + c.w - 4 && a.y > c.y + 4 && a.y < c.y + c.h - 4;
        if (nearDoor || inside) want = 1;
      });
      const cur = world.doorOpen[id] || 0;
      world.doorOpen[id] = cur + (want - cur) * Math.min(1, dt * 5);
    });
  }

  function refreshCrewBoard() {
    const el = document.getElementById('crew-board-list');
    if (!el) return;
    const rows = Object.values(agents).map((a) => {
      const c = CABINS[a.deskKey] || {};
      const busy = a.status === 'working' || a.mode === 'walk';
      const state = !a.visible
        ? 'OFFSITE'
        : a.mode === 'walk'
          ? 'WALKING'
          : (a.status === 'working' ? 'WORKING' : (a.activity || 'AT DESK'));
      const task = (a.activity || c.purpose || a.role || '—').slice(0, 36);
      const acc = c.accent || (a.look && a.look.accent) || '#22d3ee';
      return `<div class="crew-row ${busy ? 'busy' : ''} ${a.id === 'jarvis' ? 'boss' : ''}" style="--acc:${acc}">
        <span class="crew-dot"></span>
        <div class="crew-meta">
          <div class="crew-name">${a.id === 'jarvis' ? '★ ' : ''}${a.first} <em>${c.room || a.role || ''}</em></div>
          <div class="crew-job">${c.job || a.role || ''}</div>
          <div class="crew-task">${state} · ${task}</div>
        </div>
      </div>`;
    }).join('');
    el.innerHTML = rows;
  }

  function setIntercom(msg) {
    world.intercom = msg;
    world.intercomT = 5;
  }

  /** Adrian calls employee into BOSS cabin, briefs live, then they go work */
  function briefInBossOffice(agentId, command) {
    const a = agents[agentId];
    const boss = agents.jarvis;
    if (!a || !boss || !a.visible) return;
    const cmd = String(command || '').slice(0, 70);
    world.doorOpen.jarvis = 1;
    setIntercom(`INTERCOM · ${a.first} → Boss cabin`);
    setBubble('jarvis', `${a.first}, my office. Now.`, 3.5);
    setBubble(agentId, 'On my way, Adrian.', 3);

    // Boss stands ready in cabin
    const bossSit = sitPoint(CABINS.jarvis);
    walkTo(boss, bossSit.x, bossSit.y, 'work');
    boss.status = 'working';
    boss.activity = `Briefing ${a.first}`;

    a.status = 'working';
    a.activity = 'Called to boss cabin';
    const fromDoor = cabinDoorPoint(CABINS[a.deskKey] || CABINS.jarvis);
    const bossDoor = cabinDoorPoint(CABINS.jarvis);
    const guest = bossGuestSpot();
    queuePath(a, [fromDoor, { x: 460, y: 200 }, bossDoor, guest], 'idle');
    a._onArrive = () => {
      a.dir = 1; // face boss
      setBubble('jarvis', cmd || 'Here is your brief.', 4);
      setBubble(agentId, 'Understood, sir.', 3);
      setTimeout(() => {
        setBubble(agentId, 'Going to my desk.', 2.5);
        setBubble('jarvis', 'Good. Execute.', 2.5);
        boss.status = 'online';
        boss.activity = 'In boss cabin';
        if (agentId === 'waiter') {
          serveFloor(cmd);
        } else {
          goWork(agentId, cmd);
        }
        setTimeout(() => goIdleCabin('jarvis'), 1200);
      }, 2800);
    };
  }

  function serveFloor(order) {
    const w = agents.waiter;
    if (!w) return;
    w.carrying = 'tray';
    w.status = 'working';
    w.activity = order || 'Serving floor';
    setIntercom('INTERCOM · Pantry serving');
    setBubble('waiter', 'Serving the floor.', 3);
    const stops = ['hunter', 'mira', 'mail', 'calendar', 'weather', 'youtube', 'briefing', 'jarvis']
      .map((id) => {
        const c = CABINS[id];
        if (!c) return null;
        const d = cabinDoorPoint(c);
        return d;
      })
      .filter(Boolean);
    queuePath(w, stops.slice(0, 4), 'work');
    w._onArrive = () => {
      setBubble('waiter', 'Done — pantry clear.', 3);
      w.carrying = null;
      w.status = 'idle';
      goIdleCabin('waiter');
    };
  }

  function callWaiter(fromId, order) {
    const from = agents[fromId] || agents.jarvis;
    const msg = order || 'coffee and bottles';
    setIntercom(`INTERCOM · ${from.first} → Pantry: ${msg}`);
    setBubble(fromId, `Intercom: Ravi, ${msg}.`, 3);
    setBubble('waiter', 'Copy — on my way.', 3);
    const w = agents.waiter;
    if (!w) return;
    w.carrying = 'tray';
    w.status = 'working';
    const cabin = CABINS[from.deskKey] || CABINS.jarvis;
    world.doorOpen[cabin === CABINS.jarvis ? 'jarvis' : from.deskKey] = 1;
    const door = cabinDoorPoint(cabin);
    const sit = sitPoint(cabin);
    queuePath(w, [door, { x: sit.x + 12, y: sit.y }], 'idle');
    w._onArrive = () => {
      setBubble('waiter', `Here — ${msg}.`, 3);
      setBubble(fromId, 'Thanks Ravi.', 2);
      setTimeout(() => {
        w.carrying = null;
        goIdleCabin('waiter');
      }, 2000);
    };
  }

  function goWork(id, activity) {
    const a = agents[id];
    if (!a || !a.visible) return;
    if (id === 'waiter') {
      serveFloor(activity);
      return;
    }
    const cabin = CABINS[a.deskKey];
    if (!cabin) return;
    a.status = 'working';
    a.activity = activity || 'On task';
    a.nextRoam = 9999;
    world.doorOpen[a.deskKey] = 1;
    const door = cabinDoorPoint(cabin);
    const sit = sitPoint(cabin);
    queuePath(a, [door, { x: sit.x, y: sit.y }], 'work');
    setBubble(id, activity || 'At my desk…', 3.5);
  }

  function goIdleCabin(id) {
    const a = agents[id];
    if (!a) return;
    a.status = id === 'jarvis' ? 'online' : 'idle';
    a.activity = '';
    a.nextRoam = 100 + Math.random() * 140;
    const cabin = CABINS[a.deskKey];
    if (!cabin) return;
    const sit = sitPoint(cabin);
    walkTo(a, sit.x, sit.y, 'work');
  }

  function updateMover(a, dt) {
    if (a.bubbleT > 0) a.bubbleT -= dt;
    if (!a.visible) return;

    if (a.mode === 'work') {
      a.workAnim += dt;
      // Face the triple screens
      if (a.deskKey && CABINS[a.deskKey]) {
        a.dir = workstation(CABINS[a.deskKey]).face;
      } else {
        a.dir = 3;
      }
      if (a.status === 'working' || a.isGuard) return;
      // Rare coffee break only — mostly stay working at PC
      if (world.dayStarted && !a.isGuard) {
        a.nextRoam -= dt;
        if (a.nextRoam <= 0) {
          if (Math.random() < 0.45) {
            const spot = ROAM[Math.floor(Math.random() * ROAM.length)];
            const cabin = CABINS[a.deskKey];
            const door = cabinDoorPoint(cabin);
            const lines = BREAK_LINES[spot.kind] || ['Quick break.'];
            setBubble(a.id, lines[Math.floor(Math.random() * lines.length)], 2.4);
            a.activity = `${spot.label} break`;
            queuePath(a, [door, { x: spot.x, y: spot.y }], 'break');
          }
          a.nextRoam = 90 + Math.random() * 150;
        }
      }
      return;
    }

    if (a.mode === 'idle' && a._breakTimer != null) {
      a._breakTimer -= dt;
      if (a._breakTimer <= 0) {
        a._breakTimer = null;
        if (a.status !== 'working' && a.deskKey) {
          const cabin = CABINS[a.deskKey];
          const door = cabinDoorPoint(cabin);
          const sit = sitPoint(cabin);
          a.activity = '';
          queuePath(a, [door, { x: sit.x, y: sit.y }], 'work');
          setBubble(a.id, 'Back to my screens.', 2);
        }
      }
      return;
    }

    const dx = a.tx - a.x;
    const dy = a.ty - a.y;
    const dist = Math.hypot(dx, dy);
    if (dist > 1.1) {
      a.mode = 'walk';
      const speed = a.status === 'working' ? 48 : 36;
      a.x += (dx / dist) * speed * dt;
      a.y += (dy / dist) * speed * dt;
      if (Math.abs(dx) > Math.abs(dy)) a.dir = dx < 0 ? 1 : 2;
      else a.dir = dy < 0 ? 3 : 0;
      a.frameT += dt;
      if (a.frameT > 0.12) {
        a.frameT = 0;
        a.frame = (a.frame + 1) % 4;
      }
      return;
    }

    a.x = a.tx;
    a.y = a.ty;
    if (a.path.length) {
      const n = a.path.shift();
      a.tx = n.x;
      a.ty = n.y;
      a.mode = 'walk';
      return;
    }

    if (a._then === 'work') {
      a.mode = 'work';
      a._then = null;
      if (a._onArrive) { const cb = a._onArrive; a._onArrive = null; cb(); }
    } else if (a._then === 'break') {
      a.mode = 'idle';
      a._breakTimer = 2.5 + Math.random() * 2;
      a._then = null;
      if (a._onArrive) { const cb = a._onArrive; a._onArrive = null; cb(); }
    } else {
      a.mode = a._then || 'idle';
      a._then = null;
      if (a._onArrive) { const cb = a._onArrive; a._onArrive = null; cb(); }
    }
  }

  // ── Boot / open-day sequence ──
  let bootPromise = null;

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function openDaySequence() {
    if (world.dayStarted || world.bootPhase === 'guards') return;
    world.bootPhase = 'guards';
    world.bootMsg = 'Guards opening Nexus Gate…';

    // Guards walk to gate center levers
    setBubble('guard1', 'Opening gate.', 3);
    setBubble('guard2', 'Clear to enter.', 3);
    walkTo(guards.guard1, GATE.x - 10, GATE.y + 4, 'idle');
    walkTo(guards.guard2, GATE.x + GATE.w - 4, GATE.y + 4, 'idle');
    await sleep(1600);

    world.bootPhase = 'gate';
    // Animate gate open
    const t0 = performance.now();
    await new Promise((resolve) => {
      function tick(now) {
        world.gateOpen = Math.min(1, (now - t0) / 1800);
        if (world.gateOpen < 1) requestAnimationFrame(tick);
        else resolve();
      }
      requestAnimationFrame(tick);
    });
    setBubble('guard1', 'Gate open — welcome.', 3);
    world.bootMsg = 'Employees entering HQ…';

    world.bootPhase = 'enter';
    for (let i = 0; i < ENTRY_ORDER.length; i++) {
      const id = ENTRY_ORDER[i];
      const a = agents[id];
      const cabin = CABINS[a.deskKey];
      a.visible = true;
      a.status = 'idle';
      a.x = OUTSIDE.x + (i % 3) * 8 - 8;
      a.y = OUTSIDE.y;
      a.tx = a.x;
      a.ty = a.y;
      setBubble(id, id === 'jarvis' ? `${a.first} opening the floor.` : `${a.first} reporting in.`, 2.5);

      const door = cabinDoorPoint(cabin);
      const sit = sitPoint(cabin);
      // Path: outside → gate → lobby → cabin door → chair at desk
      queuePath(a, [
        { x: GATE.x + GATE.w / 2 - 8, y: GATE.y + 22 },
        { x: GATE.x + GATE.w / 2 - 8, y: GATE.y - 8 },
        { x: 220, y: 210 },
        door,
        { x: sit.x, y: sit.y },
      ], 'work');

      // Open their cabin door as they approach
      setTimeout(() => {
        const t1 = performance.now();
        function openDoor(now) {
          world.doorOpen[id] = Math.min(1, (now - t1) / 700);
          if (world.doorOpen[id] < 1) requestAnimationFrame(openDoor);
        }
        requestAnimationFrame(openDoor);
      }, 2200);

      world.bootMsg = `${a.fullName || a.name} → ${cabin.label}`;
      await sleep(1100);
    }

    await sleep(4500);
    world.dayStarted = true;
    world.bootPhase = 'done';
    world.bootMsg = 'NEXUS HQ open · all cabins staffed';
    refreshCrewBoard();
    // Snap everyone into their chair facing triple-screens
    Object.keys(agents).forEach((id) => {
      const a = agents[id];
      const cabin = CABINS[a.deskKey];
      if (!cabin) return;
      const sit = sitPoint(cabin);
      a.visible = true;
      a.x = sit.x;
      a.y = sit.y;
      a.tx = sit.x;
      a.ty = sit.y;
      a.path = [];
      a.mode = 'work';
      a.dir = workstation(cabin).face;
      a.status = id === 'jarvis' ? 'online' : 'idle';
      a.nextRoam = 120 + Math.random() * 180;
      world.doorOpen[id] = 1;
    });
    agents.jarvis.status = 'online';
    setBubble('jarvis', 'HQ is live. Assign anyone by name.', 4);
    setBubble('guard1', 'All staff inside.', 3);
    // Guards return to booths
    walkTo(guards.guard1, GATE.x - 28, GATE.y + 6, 'idle');
    walkTo(guards.guard2, GATE.x + GATE.w + 18, GATE.y + 6, 'idle');
  }

  window.__townOpenDay = function () {
    if (!bootPromise) bootPromise = openDaySequence().catch(console.warn);
    return bootPromise;
  };

  // ── Crew hooks ──
  function applyAgent(agent) {
    if (!agent || !agent.id || !agents[agent.id]) return;
    if (!world.dayStarted && world.bootPhase === 'waiting') return;
    const id = agent.id;
    const st = String(agent.status || 'idle').toLowerCase();
    if (st === 'working' || st === 'busy') goWork(id, agent.activity || 'Working…');
    else if (st === 'idle' || st === 'online' || st === 'ready') {
      if (agents[id].status === 'working') goIdleCabin(id);
      else agents[id].status = id === 'jarvis' ? 'online' : 'idle';
    }
  }

  const prevHandle = window.handleCrewEvent;
  window.handleCrewEvent = function (ev) {
    if (typeof prevHandle === 'function') prevHandle(ev);
    if (!ev) return;
    if (ev.kind === 'status' && ev.from && agents[ev.from]) {
      applyAgent({ id: ev.from, status: ev.status || 'working', activity: ev.activity || ev.text || '' });
    }
    if ((ev.kind === 'chat' || ev.kind === 'progress') && ev.from) {
      const target = ev.from === 'owner' ? 'jarvis' : ev.from;
      if (agents[target] || guards[target]) {
        setBubble(target, ev.text || '', 4);
        if (ev.kind === 'progress' && agents[target]) goWork(target, ev.text);
      }
      if (ev.to && agents[ev.to] && ev.to !== target) {
        setBubble(ev.to, `${ev.from}: ${(ev.text || '').slice(0, 36)}`, 2.5);
      }
    }
    if (ev.kind === 'task' && ev.to && agents[ev.to] && ev.to !== 'jarvis') {
      const a = agents[ev.to];
      if (!a._briefing) {
        a._briefing = true;
        briefInBossOffice(ev.to, (ev.text || 'New task').replace(/^Assigned:\s*/i, ''));
        setTimeout(() => { a._briefing = false; }, 10000);
      }
    }
    if (ev.kind === 'chat' && ev.from === 'jarvis' && ev.to && agents[ev.to]
        && /my office|intercom/i.test(ev.text || '')) {
      setBubble(ev.to, 'On my way, Adrian.', 3);
    }
  };

  const ROUTE = [
    { id: 'mira', re: /mira|short|shorts|video|clip|reel|viral|growth|image|photo|schedule\s+short/i },
    { id: 'hunter', re: /api|key|keys|hunter|groq|fish|eleven|openrouter|nvidia|gemini|anthropic|openai|claude|\.env|kai/i },
    { id: 'weather', re: /weather|forecast|temperature|how hot|how cold|nora/i },
    { id: 'mail', re: /email|gmail|inbox|unread|send mail|send email|check mail|priya/i },
    { id: 'calendar', re: /calendar|meeting|event|my schedule|ethan/i },
    { id: 'youtube', re: /youtube|open.*(video|yt)|diego/i },
    { id: 'briefing', re: /brief|good morning|start my day|morning report|sam/i },
    // Waiter last — "short about coffee" must stay Mira
    { id: 'waiter', re: /waiter|ravi|lunch|coffee|tea|water|bottle|pantry|intercom|serve|hungry|snack/i },
  ];

  const sendBtn = document.getElementById('send-btn');
  const commandInput = document.getElementById('command-input');
  const intercomBtn = document.getElementById('intercom-btn');

  function onAssignVisual() {
    if (!world.dayStarted) {
      setBubble('guard1', 'Activate Jarvis first.', 3);
      return;
    }
    const text = (commandInput && commandInput.value) || '';
    if (!text.trim()) return;
    let target = 'jarvis';
    for (const r of ROUTE) {
      if (r.re.test(text)) { target = r.id; break; }
    }
    setTimeout(() => {
      if (target === 'jarvis') {
        setBubble('jarvis', 'Handling from boss cabin.', 3);
        goIdleCabin('jarvis');
      } else if (target === 'waiter') {
        if (/intercom|call ravi|call waiter/i.test(text)) {
          callWaiter('jarvis', text.slice(0, 40));
        } else {
          const w = agents.waiter;
          if (w && !w._briefing) {
            w._briefing = true;
            briefInBossOffice('waiter', text.slice(0, 50));
            setTimeout(() => { w._briefing = false; }, 10000);
          }
        }
      } else {
        const a = agents[target];
        if (a && !a._briefing) {
          a._briefing = true;
          briefInBossOffice(target, text.slice(0, 60));
          setTimeout(() => { a._briefing = false; }, 10000);
        }
      }
    }, 200);
  }

  if (sendBtn) sendBtn.addEventListener('click', () => setTimeout(onAssignVisual, 0));
  if (commandInput) {
    commandInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') setTimeout(onAssignVisual, 0);
    });
  }
  if (intercomBtn) {
    intercomBtn.addEventListener('click', () => {
      if (!world.dayStarted) return;
      callWaiter('jarvis', 'lunch trays and bottles for the floor');
    });
  }

  canvas.addEventListener('click', (e) => {
    if (!world.dayStarted) return;
    const rect = canvas.getBoundingClientRect();
    const sx = (e.clientX - rect.left) / rect.width * W;
    const sy = (e.clientY - rect.top) / rect.height * H;
    for (const a of Object.values(agents)) {
      if (!a.visible) continue;
      if (sx >= a.x - 2 && sx <= a.x + 18 && sy >= a.y - 2 && sy <= a.y + 32) {
        if (commandInput) {
          const prompts = {
            mira: 'make a short about ',
            hunter: 'get me the groq api key',
            weather: 'weather today',
            mail: 'check my inbox',
            calendar: "what's on my calendar today",
            youtube: 'open youtube ',
            briefing: 'morning briefing',
            waiter: 'bring lunch and bottles',
            jarvis: '',
          };
          commandInput.value = prompts[a.id] || '';
          commandInput.focus();
        }
        setBubble(a.id, a.id === 'jarvis' ? 'In my cabin, sir.' : a.id === 'waiter' ? 'Pantry ready.' : 'Yes boss?', 2);
        break;
      }
    }
  });

  async function syncTown() {
    if (!world.dayStarted) return;
    try {
      const res = await fetch('/api/crew/state', { signal: AbortSignal.timeout(6000) });
      const data = await res.json();
      Object.values(data.agents || {}).forEach(applyAgent);
    } catch (_) { /* ok */ }
  }

  let ambientT = 8;
  function ambient(dt) {
    if (!world.dayStarted) return;
    if (world.intercomT > 0) world.intercomT -= dt;
    ambientT -= dt;
    if (ambientT > 0) return;
    ambientT = 7 + Math.random() * 9;
    // Occasional intercom → waiter (real office feel) — keep rare so campus stays calm
    if (Math.random() < 0.12) {
      const callers = ['mira', 'hunter', 'mail', 'calendar', 'weather', 'jarvis'];
      const who = callers[Math.floor(Math.random() * callers.length)];
      const orders = ['coffee please', 'water bottles', 'lunch tray', 'tea for two'];
      callWaiter(who, orders[Math.floor(Math.random() * orders.length)]);
      return;
    }
    const pool = [...Object.values(agents), ...Object.values(guards)]
      .filter((a) => a.visible && a.bubbleT <= 0 && a.status !== 'working');
    if (!pool.length) return;
    const a = pool[Math.floor(Math.random() * pool.length)];
    const lines = IDLE_LINES[a.id] || ['Standing by.'];
    setBubble(a.id, lines[Math.floor(Math.random() * lines.length)], 2.6);
  }

  function resize() {
    const rect = stage.getBoundingClientRect();
    // Fill the stage completely (cover) — no black letterbox corners
    const fit = Math.max(rect.width / W, rect.height / H);
    FIT = Math.max(0.75, fit);
    const cw = Math.floor(W * FIT);
    const ch = Math.floor(H * FIT);
    canvas.width = cw;
    canvas.height = ch;
    canvas.style.width = cw + 'px';
    canvas.style.height = ch + 'px';
    canvas.style.left = Math.floor((rect.width - cw) / 2) + 'px';
    canvas.style.top = Math.floor((rect.height - ch) / 2) + 'px';
    ctx.setTransform(FIT, 0, 0, FIT, 0, 0);
    ctx.imageSmoothingEnabled = false;
  }

  function render() {
    drawHQ();
    const all = [...Object.values(guards), ...Object.values(agents)]
      .filter((a) => a.visible)
      .sort((a, b) => a.y - b.y);
    all.forEach((a) => {
      drawChar(a);
      drawBubble(a);
    });
    // Boot / intercom banners — crisp readable
    if (world.bootPhase !== 'done') {
      ctx.fillStyle = 'rgba(0,0,0,0.72)';
      ctx.fillRect(40, H - 28, W - 80, 22);
      paintText(world.bootMsg || 'Starting…', W / 2, H - 12, { px: 14, color: '#fde047' });
    } else if (world.intercomT > 0 && world.intercom) {
      // Bottom banner — keep top campus labels (CAFE / HQ / ARCADE) readable
      ctx.fillStyle = 'rgba(15,23,42,0.92)';
      ctx.fillRect(70, H - 50, W - 140, 22);
      ctx.strokeStyle = '#fbbf24';
      ctx.lineWidth = 2;
      ctx.strokeRect(70, H - 50, W - 140, 22);
      paintText(world.intercom, W / 2, H - 34, { px: 13, color: '#fde047' });
    }
  }

  let last = performance.now();
  function loop(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    Object.values(agents).forEach((a) => updateMover(a, dt));
    Object.values(guards).forEach((a) => updateMover(a, dt));
    if (world.dayStarted) updateDoors(dt);
    ambient(dt);
    render();
    if (world.dayStarted && Math.floor(now / 400) !== Math.floor((now - dt * 1000) / 400)) {
      refreshCrewBoard();
    }
    if (liveEl) {
      if (!world.dayStarted) liveEl.textContent = world.bootMsg;
      else {
        const busy = Object.values(agents).filter((a) => a.status === 'working' || a.mode === 'walk');
        liveEl.textContent = busy.length
          ? busy.map((a) => {
            const room = (CABINS[a.deskKey] || {}).room || a.first;
            return `${a.first}@${room}: ${(a.activity || a.mode).slice(0, 18)}`;
          }).join(' · ')
          : 'Boss cabin center · each room auto-gate · assign a task';
      }
    }
    requestAnimationFrame(loop);
  }

  window.addEventListener('resize', resize);
  resize();
  refreshCrewBoard();
  setInterval(syncTown, 4000);
  requestAnimationFrame(loop);

  window.__agentTown = { goWork, goIdleCabin, setBubble, agents, guards, world, openDay: window.__townOpenDay };
})();
