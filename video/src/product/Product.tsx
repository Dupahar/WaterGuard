// WaterGuard product film: a user's walk through the real dashboard (captured states, scripts/capture_ui.py)
// framed by motion graphics. One grid (headline column left, window/graphic right), one type system,
// one accent. Every hit is cued to a narration word (timeline.json) and every number is real (product.json).
import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Audio, Img, staticFile, useCurrentFrame} from 'remotion';
import {C, clamp, ease, easeOut, F, FPS, H, lerp, prog, W} from '../lib';
import {fmt, Rise} from '../ui';
import {at, Box, Cv, data, loadData, PData, PEND, sEnd, sStart, short} from './plib';
import {boxCenter, CamKey, CurKey, FH, Focus, FRAME, Screen, StateKey} from './Screen';

const COL = {x: 96, w: 360};
// [narration block, chapter label, title] in playing order (blocks 13 and 14 were added after 8)
const CHAPTERS: [number, string, string][] = [
	[1, '01', 'The flood'], [2, '02', 'The problem'], [3, '03', 'Map the flood'], [4, '04', 'Who is cut off'],
	[5, '05', 'Ask the copilot'], [6, '06', 'On paper'], [7, '07', 'Where next'], [8, '08', 'Inspector agent'],
	[13, '09', 'How it looks'], [14, '10', 'Tested · on AWS'],
	[9, '11', 'Two fingerprints'], [10, '12', 'Anyone can re-run it'], [11, '13', 'Relief on evidence'], [12, '14', 'WaterGuard'],
];
const chapter = (n: number) => CHAPTERS.find((c) => c[0] === n)!;
/** the block that plays after block n */
const nextBlock = (n: number) => CHAPTERS[CHAPTERS.indexOf(chapter(n)) + 1][0];

const Mono: React.FC<{children: React.ReactNode; size?: number; color?: string; style?: React.CSSProperties}> = ({children, size = 17, color = 'rgba(255,255,255,.55)', style}) => (
	<div style={{fontFamily: F.mono, fontSize: size, letterSpacing: '0.09em', textTransform: 'uppercase', color, ...style}}>{children}</div>
);

/** visibility of a block: fade in at a, out at b */
const vis = (t: number, a: number, b: number, fi = 0.6, fo = 0.6) => Math.min(easeOut(clamp((t - a) / fi)), 1 - ease(clamp((t - (b - fo)) / fo)));

// ---------------- headline column ----------------
const Side: React.FC<{t: number; n: number; from: number; to: number; title: string; sub?: string; children?: React.ReactNode}> = ({t, n, from, to, title, sub, children}) => {
	const k = vis(t, from, to, 0.7, 0.5);
	if (k <= 0) return null;
	const ch = chapter(n);
	return (
		<div style={{position: 'absolute', left: COL.x, top: FRAME.y + 6, width: COL.w, opacity: k}}>
			<div style={{display: 'flex', alignItems: 'center', gap: 14, marginBottom: 26}}>
				<div style={{fontFamily: F.mono, fontSize: 18, color: C.orange}}>{ch[1]}</div>
				<div style={{height: 1, width: 40 * easeOut(clamp((t - from) / 0.8)), background: 'rgba(255,255,255,.35)'}} />
				<Mono>{ch[2]}</Mono>
			</div>
			<Rise t={t} at={from + 0.15} out={to - 0.45} text={title} size={52} weight={700} tracking={-0.035} />
			{sub && (
				<div style={{marginTop: 22, fontFamily: F.sans, fontSize: 22, lineHeight: 1.45, color: 'rgba(255,255,255,.68)', opacity: easeOut(clamp((t - from - 0.5) / 0.6))}}>{sub}</div>
			)}
			<div style={{marginTop: 34}}>{children}</div>
		</div>
	);
};

/** a row that slides in at `a` (used for lists in the headline column) */
const Item: React.FC<{t: number; a: number; children: React.ReactNode; dot?: string; style?: React.CSSProperties}> = ({t, a, children, dot = C.orange, style}) => {
	const k = easeOut(clamp((t - a) / 0.55));
	return (
		<div style={{display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16, opacity: k, transform: `translateX(${(1 - k) * -18}px)`, fontFamily: F.sans, fontSize: 22, color: '#fff', ...style}}>
			<div style={{width: 9, height: 9, borderRadius: 5, background: dot, flex: 'none', boxShadow: `0 0 0 ${5 * (1 - k)}px ${dot}44`}} />
			<div>{children}</div>
		</div>
	);
};

const Big: React.FC<{t: number; a: number; v: number; dec?: number; label: string; color?: string}> = ({t, a, v, dec = 0, label, color = '#fff'}) => {
	const k = easeOut(clamp((t - a) / 0.6));
	const n = lerp(0, v, easeOut(clamp((t - a) / 1.0)));
	return (
		<div style={{opacity: k, transform: `translateY(${(1 - k) * 16}px)`, marginBottom: 20}}>
			<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 64, letterSpacing: '-0.045em', color, lineHeight: 1}}>{fmt(n, dec)}</div>
			<Mono size={15} style={{marginTop: 6}}>{label}</Mono>
		</div>
	);
};

// ---------------- HUD (same frame on every shot) ----------------
const Hud: React.FC<{t: number}> = ({t}) => {
	const cur = [...CHAPTERS].reverse().find((c) => t >= sStart(c[0]) - 1.2) ?? CHAPTERS[0];
	const st: React.CSSProperties = {position: 'absolute', fontFamily: F.mono, fontSize: 14, letterSpacing: '0.1em', color: 'rgba(255,255,255,.45)', textTransform: 'uppercase'};
	const mm = Math.floor(t / 60), ss = Math.floor(t % 60).toString().padStart(2, '0');
	return (
		<div style={{position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 90, opacity: clamp(t / 1.2)}}>
			<div style={{...st, left: 48, top: 40}}><span style={{color: C.orange}}>●</span>&nbsp; WaterGuard</div>
			<div style={{...st, right: 48, top: 40}}>{cur[1]} · {cur[2]}</div>
			<div style={{...st, left: 48, bottom: 44}}>Trishuli valley · Nepal · 26 Aug 2026</div>
			<div style={{...st, right: 48, bottom: 44}}>{String(mm).padStart(2, '0')}:{ss}</div>
			<div style={{position: 'absolute', left: 48, right: 48, bottom: 32, height: 1, background: 'rgba(255,255,255,.12)'}} />
			<div style={{position: 'absolute', left: 48, bottom: 32, height: 2, marginBottom: -0.5, width: (W - 96) * clamp(t / PEND), background: 'rgba(255,255,255,.7)'}} />
			{CHAPTERS.map((c) => {
				const x = 48 + (W - 96) * (sStart(c[0]) / PEND);
				return <div key={c[0]} style={{position: 'absolute', left: x - 3, bottom: 29, width: 7, height: 7, transform: 'rotate(45deg)', border: '1px solid rgba(255,255,255,.4)', background: t >= sStart(c[0]) ? 'rgba(255,255,255,.7)' : 'transparent'}} />;
			})}
		</div>
	);
};

// ---------------- 01 the flood ----------------
const Flood: React.FC<{t: number}> = ({t}) => {
	const d = data()!;
	const k = vis(t, 0, sEnd(1) + 1.4, 1.2, 1.2);
	if (k <= 0) return null;
	const cor = d.cor;
	const [x0, y0, w0, h0] = cor.ext;
	const draw = clamp((t - at(1, 'bursts')) / (at(1, 'Nepal') + 1.2 - at(1, 'bursts')));
	const pts = cor.path.slice(0, Math.max(2, Math.floor(cor.path.length * ease(draw))));
	const head = pts[pts.length - 1];
	const z = lerp(1.18, 1.0, ease(clamp(t / 13)));
	const sh = 1000 / h0;     // fit 1000 px of height
	const left = 980;
	return (
		<AbsoluteFill style={{opacity: k}}>
			<div style={{position: 'absolute', left, top: 40, width: w0 * sh, height: h0 * sh, transform: `scale(${z})`, transformOrigin: '50% 30%'}}>
				<Img src={staticFile('data/corridor_hillshade.png')} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.5, filter: 'brightness(.6) contrast(1.3) sepia(.25) hue-rotate(180deg)'}} />
				<svg viewBox={`${x0} ${y0} ${w0} ${h0}`} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', overflow: 'visible'}}>
					<path d={'M' + pts.map((p) => p.join(',')).join('L')} fill="none" stroke={C.debris} strokeWidth={1400} strokeLinecap="round" strokeLinejoin="round" opacity={0.35} />
					<path d={'M' + pts.map((p) => p.join(',')).join('L')} fill="none" stroke={C.orange} strokeWidth={380} strokeLinecap="round" strokeLinejoin="round" />
					<circle cx={head[0]} cy={head[1]} r={900 + 300 * Math.sin(t * 6)} fill={C.orange} opacity={draw < 1 ? 0.5 : 0} />
					{cor.places.map((p) => {
						const q = clamp((t - at(1, 'morning')) / 0.6);
						return (
							<g key={p.name} opacity={q}>
								<circle cx={p.c[0]} cy={p.c[1]} r={520} fill="#fff" />
								<text x={p.c[0] + 1300} y={p.c[1] + 600} fontFamily={F.sans} fontSize={2200} fontWeight={600} fill="#fff">{p.name}</text>
							</g>
						);
					})}
				</svg>
			</div>
			<div style={{position: 'absolute', left: COL.x, top: 300, width: 900}}>
				<Mono color={C.orange} style={{opacity: clamp((t - 2.4) / 0.6)}}>26 August 2026 · Trishuli valley, Nepal</Mono>
				<div style={{height: 26}} />
				<Rise t={t} at={at(1, 'glacier') - 0.2} out={at(1, 'By') - 0.3} text="A glacier lake bursts." size={84} weight={800} />
				<div style={{position: 'absolute', top: 70}}>
					<Rise t={t} at={at(1, 'Which') - 0.15} out={sEnd(1) + 0.9} text="Which villages can we still reach?" size={84} weight={800} italicWords={['still']} style={{width: 860}} />
				</div>
			</div>
		</AbsoluteFill>
	);
};

// ---------------- 02 the problem -> WaterGuard ----------------
// three footprints of "the same" flood (same path structure, so they can morph into one)
const FOOT: number[][] = [
	[40, 120, 90, 30, 220, 40, 260, 110, 300, 190, 180, 260, 110, 230, 50, 205, 10, 170, 40, 120],
	[60, 90, 130, 20, 250, 80, 270, 150, 290, 230, 150, 250, 90, 210, 30, 170, 20, 130, 60, 90],
	[30, 150, 60, 60, 180, 20, 250, 80, 320, 140, 240, 240, 150, 240, 70, 240, 10, 220, 30, 150],
];
const footD = (n: number[]) => `M${n[0]} ${n[1]} C${n[2]} ${n[3]} ${n[4]} ${n[5]} ${n[6]} ${n[7]} C${n[8]} ${n[9]} ${n[10]} ${n[11]} ${n[12]} ${n[13]} C${n[14]} ${n[15]} ${n[16]} ${n[17]} ${n[18]} ${n[19]}Z`;
const MEAN = FOOT[0].map((_, i) => (FOOT[0][i] + FOOT[1][i] + FOOT[2][i]) / 3);

const Problem: React.FC<{t: number}> = ({t}) => {
	const a = sStart(2) - 0.6, b = sEnd(2) + 1.0;
	const k = vis(t, a, b, 0.8, 0.8);
	if (k <= 0) return null;
	const who: [string, number, string][] = [
		['Government survey', at(2, 'governments'), C.waterSoft], ['Aid-group assessment', at(2, 'aid'), C.amber], ["Insurer's loss adjuster", at(2, 'insurers'), C.green]];
	const argue = clamp((t - at(2, 'argue')) / 0.3) * (1 - clamp((t - at(2, 'relief')) / 0.6));
	const tw = at(2, 'Water');
	const merge = ease(clamp((t - (tw - 0.9)) / 0.9));
	const away = ease(clamp((t - (tw + 0.1)) / 0.7));
	const logo = easeOut(clamp((t - tw) / 0.9));
	const days = Math.floor(lerp(0, 23, easeOut(clamp((t - at(2, 'relief')) / 1.8))));
	const late = easeOut(clamp((t - at(2, 'relief') + 0.2) / 0.5)) * (1 - merge);
	// the panel uses the same grid as the product window
	const X = 560, Y = FRAME.y, PW = 1280, PH = FRAME.bar + FH;
	const drift = clamp((t - a) / (tw - a));
	return (
		<AbsoluteFill style={{opacity: k}}>
			<Side t={t} n={2} from={a} to={tw - 0.2} title="Everyone counts the damage their own way" sub="Three assessments of the same valley. None of them agree." />
			<div style={{position: 'absolute', left: X, top: Y, width: PW, height: PH, borderRadius: 18, overflow: 'hidden', opacity: 1 - away,
				transform: `scale(${1 - 0.06 * away})`, boxShadow: '0 30px 80px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.08)'}}>
				<Img src={staticFile('data/sya_s2_post.png')} style={{position: 'absolute', left: '50%', top: '50%', width: PW * 1.25, transform: `translate(-50%, -50%) scale(${1 + 0.1 * drift}) translate(${-30 * drift}px, ${-20 * drift}px)`,
					filter: 'brightness(.5) saturate(.7)'}} />
				<div style={{position: 'absolute', inset: 0, background: 'radial-gradient(ellipse at 50% 50%, rgba(11,13,17,0) 30%, rgba(11,13,17,.75) 100%)'}} />
				<svg viewBox="-40 -40 400 360" style={{position: 'absolute', left: 260, top: 60, width: 760, height: 684, overflow: 'visible'}}>
					{who.map(([w, tt, col], i) => {
						const q = clamp((t - tt) / 0.9);
						if (q <= 0) return null;
						const wob = Math.sin(t * 0.9 + i * 2.1) * 4 + argue * Math.sin(t * 16 + i * 3) * 3;
						// each assessor draws it somewhere else, at another size; they converge on one footprint
						const [ox, oy, sc] = [[-95, -55, 0.78], [85, 35, 1.12], [-35, 95, 0.62]][i];
						const u = 1 - merge;
						const pts = FOOT[i].map((v, j) => {
							const m = lerp(v, MEAN[j], merge);
							const c0 = j % 2 ? 140 : 160;
							return c0 + (m - c0) * lerp(1, sc, u) + (j % 2 ? oy : ox) * u + (j % 2 ? wob : -wob) * u;
						});
						const colr = merge > 0.5 ? C.orange : col;
						return (
							<g key={w} opacity={merge > 0 && i > 0 ? 1 - merge : 1}>
								<path d={footD(pts)} fill={colr} fillOpacity={0.12 + 0.12 * merge} stroke={colr} strokeWidth={2.4 + 1.6 * merge}
									pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - easeOut(q)} />
							</g>
						);
					})}
					{argue > 0 && [[150, 60], [230, 200], [70, 210]].map(([x, y], i) => (
						<text key={i} x={x} y={y} textAnchor="middle" fontFamily={F.sans} fontWeight={800} fontSize={38 + 6 * Math.sin(t * 8 + i)} fill="#fff" opacity={argue * (0.6 + 0.4 * Math.sin(t * 6 + i))}>≠</text>
					))}
				</svg>
				{who.map(([w, tt, col], i) => {
					const q = easeOut(clamp((t - tt) / 0.6)) * (1 - merge);
					const pos = [[330, 118], [960, 520], [180, 560]][i];
					return (
						<div key={w} style={{position: 'absolute', left: pos[0], top: pos[1] + Math.sin(t * 1.2 + i) * 6, opacity: q, transform: `translateY(${(1 - q) * 14}px)`,
							display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderRadius: 12, background: 'rgba(11,13,17,.82)', border: `1px solid ${col}66`,
							fontFamily: F.sans, fontSize: 22, fontWeight: 600, color: '#fff', whiteSpace: 'nowrap'}}>
							<div style={{width: 12, height: 12, borderRadius: 3, background: col}} />{w}
						</div>
					);
				})}
				<div style={{position: 'absolute', left: 40, right: 40, bottom: 34, opacity: late}}>
					<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10}}>
						<Mono color="#fff">Relief still waiting</Mono>
						<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 44, color: C.red, letterSpacing: '-0.03em'}}>Day {days}</div>
					</div>
					<div style={{height: 6, borderRadius: 3, background: 'rgba(255,255,255,.14)', overflow: 'hidden'}}>
						<div style={{width: `${(days / 23) * 100}%`, height: '100%', background: C.red}} />
					</div>
				</div>
			</div>
			<AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity: logo}}>
				<div style={{display: 'flex', alignItems: 'center', gap: 26, transform: `scale(${0.92 + 0.08 * logo})`}}>
					<div style={{width: 74, height: 74, borderRadius: 37, border: `6px solid ${C.orange}`, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
						<div style={{width: 30 * logo, height: 30 * logo, borderRadius: 15, background: C.orange}} />
					</div>
					<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 120, letterSpacing: '-0.05em', color: '#fff'}}>WaterGuard</div>
				</div>
				<div style={{marginTop: 26, display: 'flex', gap: 18, fontFamily: F.sans, fontSize: 34, color: 'rgba(255,255,255,.75)'}}>
					<span style={{opacity: easeOut(clamp((t - at(2, 'answers')) / 0.5))}}>One answer.</span>
					<span style={{opacity: easeOut(clamp((t - at(2, 'anyone')) / 0.5)), color: C.orange, fontFamily: F.serif, fontStyle: 'italic', fontSize: 40}}>Anyone can check it.</span>
				</div>
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

// ---------------- 03-09: the product walk-through ----------------
const Walk: React.FC<{t: number; p: PData}> = ({t, p}) => {
	const B = (s: string, b: string): Box | null => p.ui.states[s]?.boxes[b] ?? null;
	const A = sStart(3) - 0.5;
	const OUT = sEnd(9) + 1.0;
	const merkleIn = sStart(9) - 0.3, merkleOut = at(9, 'Press') - 0.4;
	const asideA = sEnd(8) + 1.0, asideB = merkleOut - 0.6;   // chapters 09-10 have the stage; the window returns as the fingerprints graphic leaves
	const enter = Math.min(easeOut(clamp((t - A) / 0.9)), 1 - ease(clamp((t - (OUT - 0.8)) / 0.8)))
		* (1 - Math.min(ease(clamp((t - asideA) / 0.7)), 1 - ease(clamp((t - asideB) / 0.7))))
		* (1 - Math.min(ease(clamp((t - merkleIn) / 0.6)), 1 - ease(clamp((t - merkleOut) / 0.6))))
		* (1 - 0.75 * Math.min(ease(clamp((t - (at(6, 'prints') + 0.2)) / 0.5)), 1 - ease(clamp((t - (sEnd(6) + 0.6)) / 0.5))));
	if (enter <= 0.001 && (t < A || t > OUT)) return null;

	const tr = B('d_trace', 'click');
	const states: StateKey[] = [
		{t: A, s: 'a_empty'},
		{t: at(3, 'date') + 0.15, s: 'a_preset'},
		{t: at(3, 'flood') + 0.25, s: 'a_progress'},
		{t: at(3, 'debris') - 0.2, s: 'b_result'},
		{t: at(4, 'before'), s: 'b_before'},
		{t: at(4, 'after'), s: 'b_after'},
		{t: at(4, 'Click') - 0.4, s: 'b_result'},
		{t: at(4, 'settlement') + 0.1, s: 'b_popup'},
		{t: at(4, 'Two') - 0.1, s: 'b_result'},
		{t: at(4, 'Damaged') + 0.1, s: 'b_bridges'},
		{t: at(5, 'Ask') + 0.15, s: 'c_ask0'},
		{t: at(5, 'English') + 0.2, s: 'c_ask_typed'},
		{t: at(5, 'The') + 0.2, s: 'c_ask1'},
		{t: at(5, 'maps') - 0.1, s: 'c_ask2'},
		{t: sStart(6) - 0.2, s: 'd_report_tab'},
		{t: at(7, 'traces') - 0.2, s: 'd_trace'},
		{t: at(8, 'inspector'), s: 'f_inspect'},
		{t: at(8, 'fetches') - 0.1, s: 'f_cell_later'},
		{t: at(8, 'Everything') - 0.1, s: 'f_cell_review'},
		{t: merkleOut, s: 'g_proof'},
		{t: at(9, 'browser') - 0.2, s: 'g_verified'},
	];
	const cam: CamKey[] = [
		{t: A, box: null},
		{t: at(3, 'Pick') - 0.2, box: [1060, 0, 540, 260]},
		{t: at(3, 'pulls') - 0.3, dur: 1.4, box: null},
		{t: at(3, 'debris') - 0.2, dur: 1.4, box: [180, 0, 900, 900], z: 1.25},
		{t: at(4, 'Flip') - 0.9, box: null},
		{t: at(4, 'Click') - 0.6, box: null},
		{t: at(4, 'settlement') + 0.2, dur: 1.2, box: B('b_popup', 'popup')},
		{t: at(4, 'Two') - 0.3, dur: 1.2, box: B('b_result', 'cut')},
		{t: at(4, 'Damaged') - 0.2, box: B('b_bridges', 'list')},
		{t: at(5, 'Ask') - 0.2, box: [1060, 380, 540, 520]},
		{t: at(5, 'maps') + 0.3, box: B('c_ask2', 'chat'), z: 1.35},
		{t: sStart(6) - 0.3, box: [1060, 420, 540, 400]},
		{t: at(7, 'click') - 0.4, dur: 1.2, box: null},
		{t: at(7, 'traces') + 0.2, dur: 1.4, box: [300, 0, 760, 900], z: 1.2},
		{t: at(7, 'lists') - 0.2, box: B('d_trace', 'out')},
		{t: at(8, 'inspector') - 0.3, box: null},
		{t: at(8, 'measures') - 0.2, box: B('f_inspect', 'first')},
		{t: at(8, 'fetches') - 0.1, box: null},
		{t: at(8, 'Everything') + 0.2, box: B('f_cell_review', 'keep') ? [200, 560, 1200, 340] : null},
		{t: merkleOut, dur: 0.01, box: B('g_proof', 'info')},
		{t: at(9, 'browser') - 0.2, box: B('g_verified', 'log')},
	];
	const cursor: CurKey[] = [
		{t: at(3, 'Pick') - 0.1, p: [1200, 300]},
		{t: at(3, 'place') + 0.1, p: boxCenter(B('a_empty', 'preset')), click: true},
		{t: at(3, 'map') - 0.05, p: boxCenter(B('a_preset', 'run')), click: true},
		{t: at(3, 'radar'), p: [640, 520]},
		{t: at(4, 'before') - 0.05, p: boxCenter(B('b_before', 'before_btn')), click: true},
		{t: at(4, 'after') - 0.05, p: boxCenter(B('b_after', 'after_btn')), click: true},
		{t: at(4, 'settlement'), p: boxCenter(B('b_popup', 'dot')), click: true},
		{t: at(4, 'Two'), p: boxCenter(B('b_result', 'cut'), 140, -30)},
		{t: at(4, 'Damaged'), p: boxCenter(B('b_bridges', 'tab')), click: true},
		{t: at(5, 'Ask'), p: boxCenter(B('c_ask0', 'tab')), click: true},
		{t: at(5, 'English') + 0.1, p: boxCenter(B('c_ask0', 'input')), click: true},
		{t: at(5, 'Nepali') - 0.1, p: boxCenter(B('c_ask_typed', 'send')), click: true},
		{t: at(5, 'shows'), p: boxCenter(B('c_ask2', 'chat'), 150, 40)},
		{t: sStart(6) + 0.1, p: boxCenter(B('d_report_tab', 'tab')), click: true},
		{t: at(6, 'prints') - 0.1, p: boxCenter(B('d_report_tab', 'en')), click: true},
		{t: at(7, 'click') - 0.05, p: boxCenter(B('d_report_tab', 'trace')), click: true},
		{t: at(7, 'upstream') + 0.25, p: boxCenter(tr), click: true},
		{t: at(7, 'lists') + 0.3, p: boxCenter(B('d_trace', 'out'), 120, 60)},
		{t: at(8, 'inspector') - 0.2, p: boxCenter(B('f_inspect', 'tab')), click: true},
		{t: at(8, 'fetches') - 0.25, p: [600, 470], click: true},
		{t: at(8, 'human') - 0.1, p: boxCenter(B('f_cell_review', 'keep')), dur: 1.0},
		{t: at(9, 'verify') + 0.25, p: boxCenter(B('g_proof', 'verify')), click: true, dur: 0.6},
	];

	const fx = (c: {c: [number, number]; z: number}) => (
		<>
			<Focus b={B('a_progress', 'progress')} cam={c} k={vis(t, at(3, 'flood') + 0.4, at(3, 'debris') - 0.3)} label="analysing open satellite data" />
			<Focus b={B('b_popup', 'popup')} cam={c} k={vis(t, at(4, 'still') - 0.5, at(4, 'Two') - 0.2)} label="64 % of houses have no road" />
			<Focus b={B('c_ask2', 'chat')} cam={c} k={vis(t, at(5, 'shows') - 0.1, sEnd(5) + 1.2)} color={C.green} pad={2} label="every number checked against the maps" />
			<Focus b={B('d_trace', 'out')} cam={c} k={vis(t, at(7, 'lists'), sEnd(7) + 0.9)} label="settlements in its way" />
			<Focus b={B('f_cell_review', 'keep')} cam={c} k={vis(t, at(8, 'waits'), sEnd(8) + 1.0)} color={C.green} label="the analyst decides" />
			<Focus b={B('g_verified', 'log')} cam={c} k={vis(t, at(9, 'blockchain') - 0.2, OUT - 0.6)} color={C.green} label="checked in your browser" />
		</>
	);

	const S = (n: number) => [sStart(n) - 0.9, sStart(nextBlock(n)) - 1.0] as [number, number];
	return (
		<>
			<Screen t={t} states={states} cam={cam} cursor={cursor} enter={enter} overlay={fx} />
			<Side t={t} n={3} from={S(3)[0]} to={S(3)[1]} title="Map the flood" sub="An area and a date. Nothing else.">
				<Item t={t} a={at(3, 'Sentinel')} dot={C.waterSoft}>Sentinel-1 radar · sees through cloud</Item>
				<Item t={t} a={at(3, 'Sentinel', 1)} dot={C.green}>Sentinel-2 imagery</Item>
				<Item t={t} a={at(3, 'Copernicus')} dot={C.amber}>Copernicus elevation model</Item>
				<Item t={t} a={at(3, 'open')} dot="#fff">OpenStreetMap · the day before</Item>
			</Side>
			<Side t={t} n={4} from={S(4)[0]} to={S(4)[1]} title="Who is cut off">
				<Big t={t} a={at(4, 'Two')} v={p.facts.cut} label="settlements lost every road" color={C.red} />
				<Big t={t} a={at(4, 'road', 1)} v={p.facts.stranded} label="people with no road left · est." />
				<Big t={t} a={at(4, 'bridges')} v={p.facts.bridges} label="bridges likely damaged" color={C.amber} />
				<Big t={t} a={at(4, 'buildings')} v={p.facts.buildings} label="buildings likely hit" color={C.amber} />
			</Side>
			<Side t={t} n={5} from={S(5)[0]} to={S(5)[1]} title="Ask in English or नेपाली" sub="It can only quote what the maps back up.">
				<Item t={t} a={at(5, 'pilot')} dot={C.green}>No data of its own: read-only tools</Item>
				<Item t={t} a={at(5, 'every')} dot={C.green}>Every number verified, or flagged</Item>
			</Side>
			<Side t={t} n={6} from={S(6)[0]} to={S(6)[1]} title="One page for the field" sub="Template-based: every number is the pipeline's.">
				<Item t={t} a={at(6, 'English')}>English</Item>
				<Item t={t} a={at(6, 'Nepali')}>नेपाली</Item>
				<Item t={t} a={at(6, 'code')} dot={C.green}>QR code: check it yourself</Item>
			</Side>
			<Side t={t} n={7} from={S(7)[0]} to={S(7)[1]} title="Where will it go next?" sub="Down the elevation model from any point upstream." />
			<Side t={t} n={8} from={S(8)[0]} to={S(8)[1]} title="An agent that looks twice">
				<AgentLoop t={t} p={p} />
			</Side>
			<Side t={t} n={9} from={S(9)[0]} to={OUT - 0.4} title="Two fingerprints" sub="Anchored on Ethereum. Checked by your own browser.">
				<Item t={t} a={at(9, 'file')} dot={C.waterSoft}>{p.files.length} files → report root</Item>
				<Item t={t} a={at(9, 'village')} dot={C.orange}>{p.settlements.length} settlements → claims root</Item>
			</Side>
			<Sitrep t={t} />
			<Merkle t={t} p={p} from={merkleIn} to={merkleOut + 0.3} />
		</>
	);
};

const AgentLoop: React.FC<{t: number; p: PData}> = ({t, p}) => {
	const steps: [string, number, string][] = [
		['Perceive', at(8, 'measures'), 'OpenCV 5 on every cell'], ['Decide', at(8, 'When'), 'confirm · look later · ask'], ['Act', at(8, 'fetches'), 'fetch a fresh image']];
	const lines: [string, number][] = [['colour', at(8, 'color')], ['structure', at(8, 'structure')], ['vegetation', at(8, 'vegetation')], ['radar', at(8, 'radar')]];
	return (
		<div>
			{steps.map(([s, a, d], i) => {
				const k = easeOut(clamp((t - a) / 0.5));
				const live = t >= a && (i === 2 || t < steps[i + 1][1]);
				return (
					<div key={s} style={{display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14, opacity: 0.35 + 0.65 * k}}>
						<div style={{width: 34, height: 34, borderRadius: 17, border: `2px solid ${live ? C.orange : 'rgba(255,255,255,.4)'}`, background: live ? C.orange + '33' : 'transparent', fontFamily: F.mono, fontSize: 15, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>{i + 1}</div>
						<div>
							<div style={{fontFamily: F.sans, fontWeight: 700, fontSize: 24, color: '#fff'}}>{s}</div>
							<Mono size={13}>{d}</Mono>
						</div>
					</div>
				);
			})}
			<div style={{display: 'flex', flexWrap: 'wrap', gap: 8, margin: '10px 0 26px 48px'}}>
				{lines.map(([l, a]) => {
					const k = easeOut(clamp((t - a) / 0.4));
					return <div key={l} style={{fontFamily: F.mono, fontSize: 14, padding: '6px 10px', borderRadius: 8, border: `1px solid ${k > 0.5 ? C.green : 'rgba(255,255,255,.2)'}`, color: k > 0.5 ? C.green : 'rgba(255,255,255,.4)', transform: `scale(${0.9 + 0.1 * k})`}}>✓ {l}</div>;
				})}
			</div>
			<div style={{display: 'flex', gap: 26, opacity: easeOut(clamp((t - at(8, 'confirms')) / 0.6))}}>
				<div><div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 46, color: C.green}}>{p.inspection.confirmed}</div><Mono size={13}>confirmed</Mono></div>
				<div><div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 46, color: '#fff'}}>{p.inspection.later_looks}</div><Mono size={13}>later looks</Mono></div>
				<div><div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 46, color: C.amber}}>{p.inspection.pending_review}</div><Mono size={13}>for a human</Mono></div>
			</div>
		</div>
	);
};

/** the printed report slides up over the window: English, then Nepali, then a zoom on the QR block */
const Sitrep: React.FC<{t: number}> = ({t}) => {
	const a = at(6, 'prints') + 0.15, b = sEnd(6) + 0.9;
	const k = vis(t, a, b, 0.8, 0.7);
	if (k <= 0) return null;
	const ne = easeOut(clamp((t - at(6, 'Nepali')) / 0.8));
	const qr = ease(clamp((t - at(6, 'code') + 0.2) / 1.0));
	const sheet = (src: string, x: number, y: number, rot: number, o: number) => (
		<div style={{position: 'absolute', left: x, top: y, width: 620, height: 877, borderRadius: 6, overflow: 'hidden', background: '#fff',
			boxShadow: '0 4px 10px rgba(0,0,0,.3), 0 40px 90px rgba(0,0,0,.5)', transform: `rotate(${rot}deg)`, opacity: o}}>
			<Img src={staticFile(`ui/${src}`)} style={{width: '100%'}} />
		</div>
	);
	// glide the QR block of the English sheet to the middle of the window area
	const z = lerp(1, 1.9, qr);
	const O = [1000, 885], T = [1200, 560];
	return (
		<div style={{position: 'absolute', inset: 0, opacity: k}}>
			<div style={{position: 'absolute', left: 0, top: 0, width: W, height: H, transform: `translateY(${(1 - k) * 80}px)`, transformOrigin: '1000px 980px'}}>
				<div style={{position: 'absolute', inset: 0, transform: `translate(${(T[0] - O[0]) * qr}px, ${(T[1] - O[1]) * qr}px) scale(${z})`, transformOrigin: `${O[0]}px ${O[1]}px`}}>
					{sheet('sitrep_ne.png', 1180 + (1 - ne) * 200, 150, 4 * ne, ne)}
					{sheet('sitrep_en.png', 690, 120, -2 * (1 - qr), 1)}
				</div>
			</div>
		</div>
	);
};

/** files and settlements fold into two roots, the roots drop into a block on the chain */
const Merkle: React.FC<{t: number; p: PData; from: number; to: number}> = ({t, p, from, to}) => {
	const k = vis(t, from, to, 0.6, 0.6);
	if (k <= 0) return null;
	const X0 = 560, X1 = 1840;
	const fold1 = ease(clamp((t - at(9, 'file')) / 1.2));
	const fold2 = ease(clamp((t - at(9, 'village')) / 1.2));
	const anchor = ease(clamp((t - at(9, 'anchored') + 0.2) / 1.0));
	const col = (items: string[], x: number, y0: number, fold: number, color: string, root: string, label: string) => {
		const n = items.length;
		const rx = x + 360, ry = y0 + 170;
		return (
			<>
				<svg style={{position: 'absolute', left: 0, top: 0, width: W, height: H, overflow: 'visible'}}>
					{items.map((_, i) => {
						const y = y0 + i * (340 / n);
						return <path key={i} d={`M${x + 250},${y + 10} C${x + 310},${y + 10} ${x + 300},${ry} ${rx - 12},${ry}`} fill="none" stroke={color} strokeWidth={1.4} opacity={0.6 * fold} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - fold} />;
					})}
				</svg>
				{items.map((it, i) => {
					const y = y0 + i * (340 / n);
					const q = easeOut(clamp((t - from - 0.2 - i * 0.03) / 0.4));
					return <div key={i} style={{position: 'absolute', left: x, top: y, width: 240, fontFamily: F.mono, fontSize: 13, color: 'rgba(255,255,255,.75)', opacity: q, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{it}</div>;
				})}
				<div style={{position: 'absolute', left: rx, top: ry - 40, opacity: fold, transform: `scale(${0.8 + 0.2 * fold}) translateX(${anchor * (1240 - rx)}px) translateY(${anchor * (720 - ry)}px)`, transformOrigin: '0 50%'}}>
					<div style={{padding: '14px 18px', borderRadius: 14, background: color + '22', border: `2px solid ${color}`, fontFamily: F.mono, fontSize: 18, color: '#fff'}}>
						<div style={{fontSize: 12, color, letterSpacing: '0.1em', marginBottom: 6}}>{label}</div>{short(root, 8, 6)}
					</div>
				</div>
			</>
		);
	};
	return (
		<div style={{position: 'absolute', inset: 0, opacity: k}}>
			<div style={{position: 'absolute', left: X0, top: FRAME.y, width: X1 - X0, height: FRAME.bar + FH, borderRadius: 18, border: '1px solid rgba(255,255,255,.08)', background: 'rgba(255,255,255,.02)'}} />
			{col(p.files, X0 + 40, FRAME.y + 40, fold1, C.waterSoft, p.report_root, 'REPORT ROOT')}
			{col(p.settlements.map((s) => s.name), X0 + 40, FRAME.y + 430, fold2, C.orange, p.claims_root, 'CLAIMS ROOT')}
			<div style={{position: 'absolute', left: 1180, top: 600, width: 560, height: 250, borderRadius: 18, border: `2px solid ${anchor > 0.5 ? C.green : 'rgba(255,255,255,.2)'}`, opacity: easeOut(clamp((t - at(9, 'Both')) / 0.6)), background: 'rgba(0,0,0,.25)'}}>
				<div style={{padding: '16px 20px', display: 'flex', justifyContent: 'space-between'}}>
					<Mono size={14}>Ethereum Sepolia · ReportRegistry</Mono>
					<Mono size={14} color={C.green} style={{opacity: anchor}}>anchored ✓</Mono>
				</div>
			</div>
		</div>
	);
};

// ---------------- 09 how it looks: one real cell, OpenCV 5 step by step (scripts/export_cv.py) ----------------
const LINES = ['colour', 'vegetation', 'structure', 'radar'];
const Pills: React.FC<{L: Record<string, boolean>; k?: number; size?: number}> = ({L, k = 1, size = 13}) => (
	<div style={{display: 'flex', gap: 6, opacity: k}}>
		{LINES.map((l) => (
			<div key={l} style={{fontFamily: F.mono, fontSize: size, padding: '4px 8px', borderRadius: 7, border: `1px solid ${L[l] ? C.green : 'rgba(255,255,255,.2)'}`,
				color: L[l] ? C.green : 'rgba(255,255,255,.35)'}}>{L[l] ? '✓' : '✕'} {l}</div>
		))}
	</div>
);
const Badge: React.FC<{k: number; color: string; children: React.ReactNode}> = ({k, color, children}) => (
	<div style={{position: 'absolute', left: 14, top: 14, opacity: k, transform: `translateY(${(1 - k) * -8}px)`, padding: '8px 12px', borderRadius: 10,
		background: 'rgba(11,13,17,.85)', border: `1.5px solid ${color}`, fontFamily: F.mono, fontSize: 15, color: '#fff', whiteSpace: 'nowrap'}}>{children}</div>
);

const CvLook: React.FC<{t: number; cv: Cv}> = ({t, cv}) => {
	const a = sStart(13) - 0.9, b = sEnd(13) + 1.0;
	const k = vis(t, a, b, 0.7, 0.7);
	if (k <= 0) return null;
	const CH = 600, s = CH / cv.window[0];
	const Y = FRAME.y + 46, X0 = 570, X1 = 1240;
	const q = (w: string, d = 0.5) => easeOut(clamp((t - at(13, w)) / d));
	const L0 = cv.trace[0].lines!, L1 = cv.trace.find((x) => x.tool === 'vision.realign')!.lines!;
	const zoom = ease(clamp((t - at(13, 'zooms') + 0.2) / 0.9));
	const ax = lerp(X1, X0, zoom);                       // the after chip moves left for the quadrant read-out
	const aligned = easeOut(clamp((t - at(13, 'change')) / 0.6));
	const drawM = clamp((t - at(13, 'finds')) / 1.2);
	const fit = ease(clamp((t - at(13, 'fit')) / 0.8));
	const mOut = 1 - ease(clamp((t - at(13, 'evidence') + 0.2) / 0.6));
	const strong = easeOut(clamp((t - at(13, 'two')) / 0.5));
	const stamp = easeOut(clamp((t - at(13, 'Confirmed') + 0.1) / 0.5));
	const [bx, by, bw, bh] = cv.cell_box;
	const quads: [string, number, number][] = [['NW', 0, 0], ['NE', 1, 0], ['SW', 0, 1], ['SE', 1, 1]];
	const steps: [string, string, string][] = [
		['Perceive', 'registration', `ECC: no lock · ${Object.values(L0).filter(Boolean).length} of 4 lines`],
		['Realign', 'finds', `SIFT + MAGSAC++ · ${cv.realign.inliers} of ${cv.realign.matches} kept`],
		['Zoom', 'zooms', 'four 300 m quadrants'],
		['Confirm', 'Confirmed', `${cv.strong_parts.join(' + ')} · ${Math.round(cv.strong_share * 100)} % of flagged ground`]];
	const chipBox: React.CSSProperties = {position: 'absolute', width: CH, height: CH, borderRadius: 12, overflow: 'hidden', boxShadow: '0 20px 60px rgba(0,0,0,.5), 0 0 0 1px rgba(255,255,255,.1)'};
	return (
		<AbsoluteFill style={{opacity: k}}>
			<Side t={t} n={13} from={a} to={b} title="OpenCV 5, step by step" sub={`One real cell in ${cv.area.split(' · ')[0]}, a held-out area. The after image is shifted 3 px.`}>
				{steps.map(([name, w, d], i) => {
					const on = q(w);
					const live = t >= at(13, w) && (i === 3 || t < at(13, steps[i + 1][1]));
					return (
						<div key={name} style={{display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14, opacity: 0.3 + 0.7 * on}}>
							<div style={{width: 34, height: 34, borderRadius: 17, border: `2px solid ${live ? (i === 3 ? C.green : C.orange) : 'rgba(255,255,255,.4)'}`,
								background: live ? (i === 3 ? C.green : C.orange) + '33' : 'transparent', fontFamily: F.mono, fontSize: 15, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 'none'}}>{i + 1}</div>
							<div>
								<div style={{fontFamily: F.sans, fontWeight: 700, fontSize: 24, color: '#fff'}}>{name}</div>
								<Mono size={13}>{d}</Mono>
							</div>
						</div>
					);
				})}
			</Side>
			{/* before */}
			<div style={{...chipBox, left: X0, top: Y, opacity: 1 - zoom}}>
				<Img src={staticFile('data/cv/pre.png')} style={{width: '100%', height: '100%'}} />
			</div>
			<Mono size={14} style={{position: 'absolute', left: X0, top: Y - 30, opacity: 1 - zoom}}>Before · Sentinel-2</Mono>
			{/* after: shifted, then re-aligned */}
			<div style={{...chipBox, left: ax, top: Y}}>
				<Img src={staticFile('data/cv/post.png')} style={{position: 'absolute', width: '100%', height: '100%'}} />
				<Img src={staticFile('data/cv/post_aligned.png')} style={{position: 'absolute', width: '100%', height: '100%', opacity: aligned}} />
				<Img src={staticFile('data/cv/flagged.png')} style={{position: 'absolute', width: '100%', height: '100%', opacity: q('evidence') * (1 - 0.5 * strong)}} />
				<svg viewBox={`0 0 ${CH} ${CH}`} style={{position: 'absolute', inset: 0, opacity: zoom}}>
					{quads.map(([p, i, j]) => {
						const z = cv.zoom.find((x) => x.part === p);
						const good = cv.strong_parts.includes(p);
						const hw = (bw / 2) * s, hh = (bh / 2) * s;
						return <rect key={p} x={bx * s + i * hw} y={by * s + j * hh} width={hw} height={hh} fill={good ? C.green : 'none'} fillOpacity={good ? 0.28 * strong : 0}
							stroke={good && strong > 0.5 ? C.green : '#fff'} strokeWidth={good && strong > 0.5 ? 4 : 2} opacity={z ? 1 : 0.35} strokeDasharray={z ? undefined : '6 6'} />;
					})}
				</svg>
				{quads.map(([p, i, j]) => (
					<div key={p} style={{position: 'absolute', left: (bx + (i * bw) / 2) * s + 8, top: (by + (j * bh) / 2) * s + 6, opacity: zoom, fontFamily: F.mono, fontSize: 15, color: '#fff', textShadow: '0 1px 4px #000'}}>{p}</div>
				))}
				<Badge k={q('off') * (1 - q('registration', 0.3))} color={C.amber}>after image shifted ({cv.realign.dx.toFixed(1)}, {cv.realign.dy.toFixed(1)}) px</Badge>
				<Badge k={q('registration') * (1 - aligned)} color={C.red}>ECC registration · no lock ✕</Badge>
				<Badge k={aligned * (1 - zoom)} color={C.green}>re-aligned · {Math.hypot(cv.realign.dx, cv.realign.dy).toFixed(2)} px recovered · {cv.realign.residual_px.toFixed(2)} px residual</Badge>
			</div>
			<Mono size={14} style={{position: 'absolute', left: ax, top: Y - 30}}>{aligned > 0.5 ? 'After · re-aligned' : 'After · 3 px off'}</Mono>
			{/* SIFT matches: all ratio-test matches, then MAGSAC++ keeps the inliers */}
			<svg style={{position: 'absolute', left: 0, top: 0, width: W, height: H, overflow: 'visible', opacity: mOut * (drawM > 0 ? 1 : 0)}}>
				{cv.matches.map(([sx, sy, dx, dy, inl], i) => {
					const d = clamp(drawM * 1.6 - (i / cv.matches.length) * 0.6);
					const col = inl ? (fit > 0 ? C.green : '#fff') : fit > 0 ? C.red : '#fff';
					const op = inl ? 0.75 + 0.25 * fit : 0.6 * (1 - 0.85 * fit);
					return (
						<g key={i} opacity={op}>
							<path d={`M${X0 + sx * s},${Y + sy * s} L${X1 + dx * s},${Y + dy * s}`} stroke={col} strokeWidth={inl ? 1.2 + 1.3 * fit : 1.1} fill="none" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - d} />
							<circle cx={X0 + sx * s} cy={Y + sy * s} r={3.5} fill={col} opacity={d > 0 ? 1 : 0} />
							<circle cx={X1 + dx * s} cy={Y + dy * s} r={3.5} fill={col} opacity={d >= 1 ? 1 : 0} />
						</g>
					);
				})}
			</svg>
			<div style={{position: 'absolute', left: X0, top: Y + CH + 26, display: 'flex', gap: 28, alignItems: 'center', opacity: drawM > 0 ? mOut : 0}}>
				<Mono size={15} color="#fff">{cv.keypoints[0]} / {cv.keypoints[1]} SIFT keypoints</Mono>
				<Mono size={15}>→ {cv.realign.matches} matches (ratio test)</Mono>
				<Mono size={15} color={C.green} style={{opacity: fit}}>→ {cv.realign.inliers} inliers (USAC MAGSAC++)</Mono>
				<Mono size={15} color={C.red} style={{opacity: fit}}>{cv.realign.matches - cv.realign.inliers} on changed ground, dropped</Mono>
			</div>
			<div style={{position: 'absolute', left: X1, top: Y + CH + 26, opacity: q('evidence') * (1 - zoom)}}>
				<Pills L={L1} />
			</div>
			{/* quadrant read-out */}
			<div style={{position: 'absolute', left: X1, top: Y, width: CH, opacity: zoom}}>
				<Mono size={14} color={C.orange}>vision.zoom · same measures per 300 m quadrant</Mono>
				{quads.map(([p], i) => {
					const z = cv.zoom.find((x) => x.part === p);
					const good = cv.strong_parts.includes(p);
					const r = easeOut(clamp((t - at(13, 'quarter') - 0.15 * i) / 0.5));
					return (
						<div key={p} style={{marginTop: 18, padding: '14px 16px', borderRadius: 12, opacity: r * (z ? (strong > 0 && !good ? 1 - 0.55 * strong : 1) : 0.4),
							border: `1.5px solid ${good && strong > 0.5 ? C.green : 'rgba(255,255,255,.12)'}`, background: good && strong > 0.5 ? C.green + '14' : 'rgba(255,255,255,.03)'}}>
							<div style={{display: 'flex', justifyContent: 'space-between', marginBottom: 10}}>
								<div style={{fontFamily: F.sans, fontWeight: 700, fontSize: 24, color: '#fff'}}>{p}</div>
								<Mono size={14}>{z ? `${z.impact_ha} ha flagged` : 'too little flagged'}</Mono>
							</div>
							{z && <Pills L={z.lines} />}
						</div>
					);
				})}
			</div>
			<div style={{position: 'absolute', left: X1, top: Y + CH + 18, opacity: stamp, transform: `scale(${0.9 + 0.1 * stamp})`, transformOrigin: '0 50%', display: 'flex', alignItems: 'center', gap: 22}}>
				<div style={{padding: '10px 22px', borderRadius: 14, border: `3px solid ${C.green}`, fontFamily: F.sans, fontWeight: 800, fontSize: 40, color: C.green}}>CONFIRMED</div>
				<Mono size={14}>ECC alone: sent to a human</Mono>
			</div>
		</AbsoluteFill>
	);
};

// ---------------- 10 tested the hard way, and where it runs ----------------
const Tested: React.FC<{t: number; cv: Cv}> = ({t, cv}) => {
	const a = sStart(14) - 0.9, b = sEnd(14) + 1.0;
	const k = vis(t, a, b, 0.7, 0.7);
	if (k <= 0) return null;
	const q = (w: string, d = 0.5) => easeOut(clamp((t - at(14, w)) / d));
	const X = 560, Y = FRAME.y;
	const chart = 1 - ease(clamp((t - at(14, 'runs') + 0.4) / 0.6));
	const arch = easeOut(clamp((t - at(14, 'runs') + 0.1) / 0.8));
	const shifts = [0, 1.5, 3, 5];
	const R = (sh: number, v: string) => cv.robustness.find((r) => r.shift_px === sh && r.variant === v)!;
	const base = Y + 720, MAXH = 560, GW = 300, BW = 100;
	const grow = (i: number) => ease(clamp((t - at(14, 'shift') - 0.25 * i) / 0.9));
	const hi3 = q('alone');
	const falseK = q('false');
	// boxes in the 1800 x 1050 architecture figure (docs/figures/architecture.png)
	const AS = 1280 / 1800;
	const hl: [string, number[]][] = [['Docker', [740, 128, 995, 737]], ['behind', [450, 140, 250, 78]], ['Bedrock', [450, 478, 250, 124]], ['decision', [450, 612, 250, 124]]];
	const cur = [...hl].reverse().find(([w]) => t >= at(14, w) - 0.1);
	return (
		<AbsoluteFill style={{opacity: k}}>
			<Side t={t} n={14} from={a} to={b} title={arch > 0.5 ? 'Where it runs' : 'Tested the hard way'}
				sub={arch > 0.5 ? 'One container on AWS, ap-south-1.' : `Held-out areas, ${R(0, 'agent').cells} cells. After images shifted by a known amount.`}>
				<div style={{opacity: falseK * (1 - arch), transform: `scale(${0.9 + 0.1 * falseK})`, transformOrigin: '0 50%', display: 'inline-block', padding: '16px 22px', borderRadius: 16, border: `3px solid ${C.green}`, background: C.green + '18'}}>
					<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 54, color: C.green, lineHeight: 1}}>{cv.robustness.reduce((n, r) => n + r.false_confirmations, 0)}</div>
					<Mono size={14} color="#fff" style={{marginTop: 6}}>false confirmations · any shift</Mono>
				</div>
				{arch > 0.5 && (
					<>
						<Item t={t} a={at(14, 'Docker')} dot={C.orange}>EC2 · Docker container</Item>
						<Item t={t} a={at(14, 'behind')} dot={C.orange}>CloudFront · the only way in</Item>
						<Item t={t} a={at(14, 'Bedrock')} dot={C.orange}>Amazon Bedrock · copilot</Item>
						<Item t={t} a={at(14, 'decision')} dot={C.orange}>CloudWatch · agent metrics</Item>
					</>
				)}
			</Side>
			<div style={{position: 'absolute', inset: 0, opacity: chart}}>
				<Mono size={15} color={C.orange} style={{position: 'absolute', left: X, top: Y + 6}}>Real damage confirmed with no human · held-out · python -m waterguard.validate --robustness</Mono>
				<div style={{position: 'absolute', left: X, top: Y + 44, display: 'flex', gap: 30}}>
					<Mono size={14} color="#fff"><span style={{color: 'rgba(255,255,255,.45)'}}>■</span> registration only (ECC)</Mono>
					<Mono size={14} color="#fff"><span style={{color: C.orange}}>■</span> with re-align + zoom</Mono>
				</div>
				<div style={{position: 'absolute', left: X, top: base, width: GW * 4, height: 1, background: 'rgba(255,255,255,.3)'}} />
				{shifts.map((sh, i) => {
					const g = grow(i);
					const dim = hi3 > 0 && sh !== 3 ? 1 - 0.55 * hi3 : 1;
					return (
						<div key={sh} style={{opacity: dim}}>
							{(['ecc_only', 'agent'] as const).map((v, j) => {
								const val = R(sh, v).real_damage_ha_auto_confirmed_pct;
								const h = (val / 60) * MAXH * g;
								const x = X + i * GW + 40 + j * (BW + 14);
								const col = v === 'agent' ? C.orange : 'rgba(255,255,255,.45)';
								const big = sh === 3 && hi3 > 0;
								return (
									<React.Fragment key={v}>
										<div style={{position: 'absolute', left: x, top: base - h, width: BW, height: h, background: col, borderRadius: '6px 6px 0 0'}} />
										<div style={{position: 'absolute', left: x - 20, width: BW + 40, top: base - h - (big ? 58 : 36), textAlign: 'center', opacity: g,
											fontFamily: F.sans, fontWeight: 800, fontSize: big ? 44 : 26, color: v === 'agent' ? '#fff' : big ? C.red : 'rgba(255,255,255,.7)'}}>{(val * g).toFixed(1)}%</div>
									</React.Fragment>
								);
							})}
							<Mono size={16} color="#fff" style={{position: 'absolute', left: X + i * GW + 40, width: 2 * BW + 14, top: base + 14, textAlign: 'center'}}>{sh} px shift</Mono>
						</div>
					);
				})}
			</div>
			<div style={{position: 'absolute', left: X, top: Y + 10, width: 1280, height: 1050 * AS, opacity: arch, transform: `scale(${0.97 + 0.03 * arch})`, borderRadius: 14, overflow: 'hidden',
				boxShadow: '0 30px 80px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.08)'}}>
				<Img src={staticFile('data/cv/architecture.png')} style={{width: '100%', height: '100%'}} />
				{hl.map(([w, [x, y, bw, bh]]) => {
					const on = easeOut(clamp((t - at(14, w) + 0.1) / 0.4));
					const live = cur && cur[0] === w;
					return <div key={w} style={{position: 'absolute', left: x * AS - 4, top: y * AS - 4, width: bw * AS + 8, height: bh * AS + 8, borderRadius: 12,
						border: `3px solid ${C.orange}`, opacity: on * (live ? 1 : 0.35), boxShadow: live ? `0 0 24px ${C.orange}` : 'none'}} />;
				})}
			</div>
		</AbsoluteFill>
	);
};

// ---------------- 10 anyone can re-run it ----------------
const Rerun: React.FC<{t: number; p: PData}> = ({t, p}) => {
	const a = sStart(10) - 0.9, b = sEnd(10) + 1.0;
	const k = vis(t, a, b, 0.7, 0.7);
	if (k <= 0) return null;
	const L = p.ledger;
	const ev: {t: number; title: string; sub: string; tx?: string; color: string}[] = [
		{t: at(10, 'first'), title: 'Report published', sub: 'operator · version 1', tx: L.published_v1, color: C.waterSoft},
		{t: at(10, 'disputed'), title: 'Disputed', sub: `independent re-run: ${L.dispute.village} ${fmt(L.dispute.verifier)} ≠ ${fmt(L.dispute.ours)} people stranded`, tx: L.disputed, color: C.red},
		{t: at(10, 'froze'), title: 'Payouts frozen', sub: 'a disputed report pays nothing', color: C.red},
		{t: at(10, 'bug'), title: 'Bug found & fixed', sub: 'OSM order changed which houses were sampled', color: C.amber},
		{t: at(10, 'published'), title: 'Published again', sub: 'version 2', tx: L.published_v2, color: C.waterSoft},
		{t: at(10, 'laptop'), title: 'Confirmed · laptop', sub: 'Windows · empty folder · fresh downloads', tx: L.confirmed_laptop, color: C.green},
		{t: at(10, 'server'), title: 'Confirmed · AWS server', sub: 'Linux · separate machine', tx: L.confirmed_aws, color: C.green},
	];
	const X = 560, Y = FRAME.y + 10;
	const fin = easeOut(clamp((t - at(10, 'exactly')) / 0.6));
	return (
		<AbsoluteFill style={{opacity: k}}>
			<Side t={t} n={10} from={a} to={b} title="Anyone can re-run it" sub="Open data, open code: a disagreement freezes the money.">
				<div style={{opacity: fin, marginTop: 6}}>
					<Mono size={14} color={C.green}>same claims root, byte for byte</Mono>
					<div style={{fontFamily: F.mono, fontSize: 22, color: '#fff', marginTop: 8}}>{short(p.claims_root, 8, 6)}</div>
				</div>
			</Side>
			<div style={{position: 'absolute', left: X + 22, top: Y, width: 2, height: 760, background: 'rgba(255,255,255,.12)'}} />
			{ev.map((e, i) => {
				const q = easeOut(clamp((t - e.t + 0.15) / 0.55));
				const y = Y + i * 108;
				return (
					<div key={i} style={{position: 'absolute', left: X, top: y, display: 'flex', gap: 28, alignItems: 'flex-start', opacity: q, transform: `translateY(${(1 - q) * 18}px)`}}>
						<div style={{width: 46, height: 46, borderRadius: 23, background: '#0b0d11', border: `3px solid ${e.color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 'none'}}>
							<div style={{width: 16, height: 16, borderRadius: 8, background: e.color}} />
						</div>
						<div>
							<div style={{fontFamily: F.sans, fontWeight: 700, fontSize: 30, color: '#fff'}}>{e.title}</div>
							<div style={{display: 'flex', gap: 20, marginTop: 4}}>
								<Mono size={15} color="rgba(255,255,255,.6)">{e.sub}</Mono>
								{e.tx && <Mono size={15} color={e.color}>tx {short(e.tx, 6, 4)}</Mono>}
							</div>
						</div>
					</div>
				);
			})}
			<div style={{position: 'absolute', left: 1500, top: Y + 30, opacity: fin, transform: `scale(${0.85 + 0.15 * fin})`, padding: '26px 32px', borderRadius: 20, border: `3px solid ${C.green}`, background: C.green + '18', textAlign: 'center'}}>
				<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 64, color: C.green}}>FINAL</div>
				<Mono size={15} color="#fff">3 confirmations · 2 needed</Mono>
			</div>
		</AbsoluteFill>
	);
};

// ---------------- 11 relief on evidence ----------------
const Relief: React.FC<{t: number; p: PData}> = ({t, p}) => {
	const a = sStart(11) - 0.9, b = sEnd(11) + 1.1;
	const k = vis(t, a, b, 0.7, 0.7);
	if (k <= 0) return null;
	const L = p.ledger, T = L.fund_terms;
	const pays = L.payouts as {name: string; people: number; eth: number; capped: boolean; tx: string}[];
	const t0 = at(11, 'paid');
	const step = (at(11, 'proofs') - t0) / 3;
	const paid = pays.reduce((s, x, i) => s + x.eth * easeOut(clamp((t - (t0 + i * step) - 0.5) / 0.8)), 0);
	return (
		<AbsoluteFill style={{opacity: k}}>
			<Side t={t} n={11} from={a} to={b} title="Relief that moves on evidence" sub="Set up before the flood. Paid from the proofs.">
				<Item t={t} a={at(11, 'fixed')}>{T.per_person} ETH per stranded person</Item>
				<Item t={t} a={at(11, 'capped')}>capped at {T.cap} ETH per village</Item>
				<Item t={t} a={at(11, 'final')} dot={C.green}>only once the report is final</Item>
			</Side>
			<div style={{position: 'absolute', left: 560, top: FRAME.y + 10, width: 520, padding: 28, borderRadius: 20, border: '2px solid rgba(255,255,255,.18)', background: 'rgba(255,255,255,.03)', opacity: easeOut(clamp((t - at(11, 'relief')) / 0.6))}}>
				<Mono size={14} color={C.orange}>ReliefFund #0 · Ethereum Sepolia</Mono>
				<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 56, color: '#fff', marginTop: 10}}>{fmt(T.deposit - paid, 5)} <span style={{fontSize: 26}}>ETH</span></div>
				<Mono size={13}>left in the fund · {short(L.fund, 6, 4)}</Mono>
			</div>
			{pays.map((x, i) => {
				const s = t0 + i * step;
				const q = easeOut(clamp((t - s) / 0.6));
				const fly = ease(clamp((t - s - 0.3) / 0.8));
				const y = FRAME.y + 300 + i * 150;
				return (
					<React.Fragment key={x.tx}>
						<div style={{position: 'absolute', left: 560, top: y, width: 620, opacity: q, transform: `translateX(${(1 - q) * -20}px)`, padding: '18px 22px', borderRadius: 16, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.1)'}}>
							<div style={{display: 'flex', justifyContent: 'space-between', fontFamily: F.sans, fontSize: 28, fontWeight: 700, color: '#fff'}}>
								<span>{x.name}</span><span style={{color: C.green}}>{x.eth} ETH</span>
							</div>
							<div style={{display: 'flex', justifyContent: 'space-between', marginTop: 6}}>
								<Mono size={14}>{fmt(x.people)} people stranded{x.capped ? ' · capped' : ''}</Mono>
								<Mono size={14} color={C.green}>tx {short(x.tx, 6, 4)}</Mono>
							</div>
						</div>
						<div style={{position: 'absolute', left: lerp(1190, 1500, fly), top: lerp(y + 40, FRAME.y + 470, fly), width: 22, height: 22, borderRadius: 11, background: C.green, opacity: fly > 0 && fly < 1 ? 1 : 0, boxShadow: `0 0 20px ${C.green}`}} />
					</React.Fragment>
				);
			})}
			<div style={{position: 'absolute', left: 1460, top: FRAME.y + 380, width: 340, padding: 26, borderRadius: 20, border: `2px solid ${C.green}`, background: C.green + '14', opacity: easeOut(clamp((t - t0) / 0.6)), textAlign: 'center'}}>
				<Mono size={14} color={C.green}>Relief partner · district office</Mono>
				<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 56, color: '#fff', marginTop: 8}}>{fmt(paid, 5)}</div>
				<Mono size={13}>ETH received · 3 villages</Mono>
			</div>
		</AbsoluteFill>
	);
};

// ---------------- 12 close ----------------
const Close: React.FC<{t: number; p: PData}> = ({t, p}) => {
	const a = sStart(12) - 0.9;
	const k = vis(t, a, PEND + 5, 0.8, 0.8);
	if (k <= 0) return null;
	const ho = p.validation.filter((v) => v.split === 'held-out');
	const end = easeOut(clamp((t - at(12, 'This') + 0.3) / 0.9));
	const stats = 1 - ease(clamp((t - (at(12, 'from') - 0.6)) / 0.6));
	return (
		<AbsoluteFill style={{opacity: k}}>
			<div style={{position: 'absolute', left: COL.x, top: FRAME.y + 6, opacity: stats}}>
				<Mono color={C.orange}>{chapter(12)[1]} · Checked against the official EU damage maps · held-out areas</Mono>
				<div style={{display: 'flex', gap: 120, marginTop: 50}}>
					{ho.map((v, i) => {
						const s = at(12, '0', i);
						const q = easeOut(clamp((t - s) / 0.6));
						return (
							<div key={v.aoi} style={{opacity: q}}>
								<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 210, letterSpacing: '-0.06em', color: '#fff', lineHeight: 1}}>{lerp(0, v.f1, easeOut(clamp((t - s) / 1.0))).toFixed(2)}</div>
								<Mono size={20} style={{marginTop: 10}}>F1 · {v.name}</Mono>
							</div>
						);
					})}
					<div style={{opacity: easeOut(clamp((t - at(12, 'European')) / 0.6))}}>
						<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 210, letterSpacing: '-0.06em', color: C.green, lineHeight: 1}}>{p.inspector_eval['held-out'].confirmed_that_are_real_pct}<span style={{fontSize: 90}}>%</span></div>
						<Mono size={20} style={{marginTop: 10}}>of agent-confirmed cells are real damage</Mono>
					</div>
				</div>
			</div>
			<AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
				<div style={{position: 'absolute', top: 330, width: 1600, textAlign: 'center'}}>
					<div style={{display: 'flex', justifyContent: 'center'}}>
						<Rise t={t} at={at(12, 'from') - 0.4} out={at(12, 'This') - 0.5} text="Floods from space." size={110} weight={800} />
					</div>
					<div style={{display: 'flex', justifyContent: 'center', marginTop: 10}}>
						<Rise t={t} at={at(12, 'Answers') - 0.1} out={at(12, 'This') - 0.5} text="Answers anyone can verify." size={110} weight={800} italicWords={['verify.']} accent={{'verify.': C.orange}} />
					</div>
				</div>
				<div style={{opacity: end, transform: `scale(${0.94 + 0.06 * end})`, display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
					<div style={{display: 'flex', alignItems: 'center', gap: 26}}>
						<div style={{width: 74, height: 74, borderRadius: 37, border: `6px solid ${C.orange}`, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
							<div style={{width: 30, height: 30, borderRadius: 15, background: C.orange}} />
						</div>
						<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 120, letterSpacing: '-0.05em', color: '#fff'}}>WaterGuard</div>
					</div>
					<div style={{display: 'flex', gap: 40, marginTop: 40}}>
						<Mono size={22} color="#fff">d1sgb39rsg0dlm.cloudfront.net</Mono>
						<Mono size={22}>github.com/Dupahar/WaterGuard</Mono>
					</div>
					<div style={{marginTop: 46, opacity: easeOut(clamp((t - at(12, 'This') - 1.4) / 0.8)), textAlign: 'center'}}>
						<Mono size={15} color={C.orange}>Team</Mono>
						<div style={{fontFamily: F.sans, fontSize: 34, fontWeight: 700, color: '#fff', marginTop: 8}}>Adil Mahajan</div>
						<Mono size={14} style={{marginTop: 6}}>student · design, data, code</Mono>
					</div>
					<Mono size={15} style={{marginTop: 34}}>Contains modified Copernicus Sentinel data 2026 · Copernicus DEM · © OpenStreetMap contributors</Mono>
				</div>
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

export const Product: React.FC = () => {
	const [d, setD] = useState(data());
	useEffect(() => {
		if (!d) loadData().then(setD);
	}, [d]);
	const frame = useCurrentFrame();
	const t = frame / FPS;
	return (
		<AbsoluteFill style={{background: C.ink, fontFamily: F.sans, overflow: 'hidden'}}>
			<AbsoluteFill style={{backgroundImage: 'radial-gradient(rgba(255,255,255,.05) 1px, transparent 1px)', backgroundSize: '36px 36px', opacity: 0.6}} />
			{d && (
				<>
					<Flood t={t} />
					<Problem t={t} />
					<Walk t={t} p={d.p} />
						<CvLook t={t} cv={d.cv} />
						<Tested t={t} cv={d.cv} />
					<Rerun t={t} p={d.p} />
					<Relief t={t} p={d.p} />
					<Close t={t} p={d.p} />
				</>
			)}
			<Hud t={t} />
			<Audio src={staticFile('audio/product_mix.wav')} />
		</AbsoluteFill>
	);
};
export const PRODUCT_FRAMES = Math.round(PEND * FPS);
