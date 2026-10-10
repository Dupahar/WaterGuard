// WaterGuard launch film. Same grammar as the Tawi Twin film: circle-reveal layers, one camera,
// every hit cued to a word of the narration (timeline.json), every map and number from real runs.
import React, {useEffect, useState} from 'react';
import {AbsoluteFill, continueRender, delayRender, Img, staticFile, useCurrentFrame} from 'remotion';
import {C, clamp, cue, Data, ease, easeOut, END, F, FPS, getData, H, lerp, prog, Run, sceneStart, useDataOnce, W, win, XY} from './lib';
import {Abs, Center, count, fmt, HUD, lift, Phone, Pill, Rise, Tool, typed} from './ui';

// ---------------- layers ----------------
type Layer = {from: number; bg: string; dark: boolean; o: [number, number]; dur?: number; render: (t: number, d: Data) => React.ReactNode};
const Reveal: React.FC<{t: number; L: Layer; children: React.ReactNode}> = ({t, L, children}) => {
	const k = prog(t, L.from, L.dur ?? 0.8);
	const r = k * Math.hypot(W, H) * 1.05;
	return (
		<AbsoluteFill style={{background: L.bg, clipPath: k >= 1 ? undefined : `circle(${r}px at ${L.o[0]}px ${L.o[1]}px)`}}>{children}</AbsoluteFill>
	);
};

// ---------------- camera (world metres -> screen) ----------------
type Cam = {x: number; y: number; z: number; rot: number};
type Move = {at: number; dur: number; to: Partial<Cam>};
const cam = (t: number, init: Cam, moves: Move[]): Cam => {
	let s = {...init};
	for (const m of moves) {
		const k = prog(t, m.at, m.dur);
		if (k <= 0) break;
		const g = {...s, ...m.to};
		s = {x: lerp(s.x, g.x, k), y: lerp(s.y, g.y, k), z: Math.exp(lerp(Math.log(s.z), Math.log(g.z), k)), rot: lerp(s.rot, g.rot, k)};
	}
	return s;
};
const proj = (c: Cam, p: XY): XY => {
	const r = (c.rot * Math.PI) / 180;
	const dx = (p[0] - c.x) * c.z, dy = (p[1] - c.y) * c.z;
	return [W / 2 + dx * Math.cos(r) - dy * Math.sin(r), H / 2 + dx * Math.sin(r) + dy * Math.cos(r)];
};
const tf = (c: Cam) => `translate(${W / 2} ${H / 2}) rotate(${c.rot}) scale(${c.z}) translate(${-c.x} ${-c.y})`;
const pathD = (pts: XY[], close = false) => 'M' + pts.map((p) => `${p[0]},${p[1]}`).join('L') + (close ? 'Z' : '');

/** A raster (real PNG) placed in world metres under the camera. */
const Raster: React.FC<{c: Cam; src: string; ext: [number, number, number, number]; opacity?: number; filter?: string; clip?: number; pixelated?: boolean}> = ({c, src, ext, opacity = 1, filter, clip, pixelated}) => (
	<div style={{position: 'absolute', inset: 0, overflow: 'hidden', opacity}}>
		<div style={{position: 'absolute', left: 0, top: 0, width: W, height: H, transform: `translate(${W / 2}px, ${H / 2}px) rotate(${c.rot}deg) scale(${c.z}) translate(${-c.x}px, ${-c.y}px)`, transformOrigin: '0 0'}}>
			<Img
				src={staticFile(`data/${src}`)}
				style={{
					position: 'absolute',
					left: ext[0],
					top: ext[1],
					width: ext[2],
					height: ext[3],
					filter,
					imageRendering: pixelated ? 'pixelated' : 'auto',
					clipPath: clip !== undefined ? `inset(0 ${(1 - clip) * 100}% 0 0)` : undefined,
					// feather the raster's edges into the background
					WebkitMaskImage: 'linear-gradient(to right, transparent 0%, #000 7%, #000 93%, transparent 100%), linear-gradient(to bottom, transparent 0%, #000 5%, #000 95%, transparent 100%)',
					WebkitMaskComposite: 'source-in',
					maskImage: 'linear-gradient(to right, transparent 0%, #000 7%, #000 93%, transparent 100%), linear-gradient(to bottom, transparent 0%, #000 5%, #000 95%, transparent 100%)',
					maskComposite: 'intersect',
				}}
			/>
		</div>
	</div>
);

const Mono: React.FC<{children: React.ReactNode; style?: React.CSSProperties; color?: string; size?: number}> = ({children, style, color = 'rgba(255,255,255,.6)', size = 18}) => (
	<div style={{fontFamily: F.mono, fontSize: size, letterSpacing: '0.1em', textTransform: 'uppercase', color, ...style}}>{children}</div>
);

const Tag: React.FC<{c: Cam; p: XY; k: number; children: React.ReactNode; dot?: string; dx?: number; dy?: number}> = ({c, p, k, children, dot = '#fff', dx = 20, dy = -20}) => {
	if (k <= 0) return null;
	const [x, y] = proj(c, p);
	return (
		<>
			<div style={{position: 'absolute', left: x - 10, top: y - 10, width: 20, height: 20, borderRadius: 10, background: dot, border: '3px solid #0b0d11', transform: `scale(${easeOut(clamp(k * 1.4))})`, boxShadow: `0 0 0 ${6 + 10 * (1 - k)}px rgba(255,255,255,.12)`}} />
			<div style={{position: 'absolute', left: x + dx, top: y + dy - 24, opacity: k, transform: `translateY(${(1 - k) * 14}px)`, background: 'rgba(11,13,17,0.85)', border: '1px solid rgba(255,255,255,.14)', borderRadius: 12, padding: '10px 16px', color: '#fff', fontFamily: F.sans, fontSize: 24, fontWeight: 600, whiteSpace: 'nowrap', boxShadow: lift(k, true)}}>
				{children}
			</div>
		</>
	);
};

/** Big stat on the left: number + caption */
const Stat: React.FC<{t: number; at: number; value: number; dec?: number; unit?: string; label: string; color?: string; size?: number}> = ({t, at, value, dec = 0, unit = '', label, color = '#fff', size = 150}) => {
	const k = prog(t, at - 0.15, 0.6, easeOut);
	if (k <= 0) return null;
	return (
		<div style={{opacity: k, transform: `translateY(${(1 - k) * 30}px)`, marginBottom: 26}}>
			<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: size, letterSpacing: '-0.05em', color, lineHeight: 0.95}}>
				{fmt(count(t, at, 1.0, value), dec)}
				<span style={{fontSize: size * 0.36, letterSpacing: '-0.02em', marginLeft: 10}}>{unit}</span>
			</div>
			<Mono size={20} style={{marginTop: 6}} color="rgba(255,255,255,.7)">
				{label}
			</Mono>
		</div>
	);
};

// ---------------- 01 the night: the corridor ----------------
const Night: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const cor = d.cor;
	const draw = prog(t, cue(1, 'wall'), cue(1, 'valley') + 0.8 - cue(1, 'wall'), (x) => x);
	const pts = cor.path;
	const n = Math.max(2, Math.floor(pts.length * draw));
	const head = pts[n - 1];
	// camera: hover over the glacier end, follow the debris front, then pull out to all 70 km
	const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
	const mid: XY = [(Math.min(...xs) + Math.max(...xs)) / 2 - 3500, (Math.min(...ys) + Math.max(...ys)) / 2];
	const lagged = pts[Math.max(0, n - 1 - 25)];
	const kf = prog(t, cue(1, 'wall') - 0.6, 1.2);
	const pull = prog(t, cue(1, 'roads') - 0.4, 2.6);
	const zi = Math.exp(lerp(Math.log(lerp(0.075, 0.05, prog(t, 0, 6))), Math.log(0.0185), pull));
	const fx = lerp(pts[0][0] - 2500, lagged[0], kf), fy = lerp(pts[0][1] + 3000, lagged[1], kf);
	const c: Cam = {x: lerp(fx, mid[0], pull), y: lerp(fy, mid[1], pull), z: zi, rot: 0};
	const glacier = prog(t, cue(1, 'glacier'), 0.5, easeOut);
	const strike = (w: string) => prog(t, cue(1, w) + 0.25, 0.35);
	return (
		<AbsoluteFill>
			<Raster c={c} src="corridor_hillshade.png" ext={cor.ext} opacity={0.55 + 0.1 * glacier} filter="brightness(0.55) contrast(1.25) sepia(0.25) hue-rotate(180deg)" />
			<AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 45%, rgba(11,13,17,0) 30%, rgba(11,13,17,.85) 100%)'}} />
			<svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
				<g transform={tf(c)}>
					{draw > 0 && <path d={pathD(pts.slice(0, n))} fill="none" stroke={C.orange} strokeWidth={10 / c.z} strokeLinecap="round" strokeLinejoin="round" style={{filter: 'drop-shadow(0 0 30px rgba(255,106,43,.9))'}} />}
					{draw > 0 && <path d={pathD(pts.slice(0, n))} fill="none" stroke="#ffd2b8" strokeWidth={3 / c.z} strokeLinecap="round" />}
					{draw > 0 && draw < 1 && <circle cx={head[0]} cy={head[1]} r={(16 + 6 * Math.sin(t * 20)) / c.z} fill="#fff" opacity={0.9} />}
				</g>
			</svg>
			{/* glacier pulse at the top of the corridor */}
			{glacier > 0 && (() => {
				const [x, y] = proj(c, pts[0]);
				const r = 20 + 220 * prog(t, cue(1, 'glacier'), 1.6, easeOut);
				return <div style={{position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: '50%', border: '3px solid #cfe3ff', opacity: 1 - prog(t, cue(1, 'glacier'), 1.6)}} />;
			})()}
			{cor.places.map((p, i) => {
				const idx = pts.reduce((b, q, j) => (Math.hypot(q[0] - p.c[0], q[1] - p.c[1]) < Math.hypot(pts[b][0] - p.c[0], pts[b][1] - p.c[1]) ? j : b), 0);
				const k = draw * pts.length > idx ? prog(t, cue(1, 'wall') + (idx / pts.length) * (cue(1, 'valley') + 0.8 - cue(1, 'wall')), 0.5, easeOut) : 0;
				return (
					<Tag key={i} c={c} p={p.c} k={k * (1 - prog(t, cue(1, 'roads') - 0.2, 0.4))} dot={C.orange}>
						{p.name}
					</Tag>
				);
			})}
			<Abs style={{left: 120, top: 150, opacity: win(t, 0.4, cue(1, 'wall'), 0.6, 0.5)}}>
				<Mono size={22}>25.08.2026 · 22:00 UTC · Rasuwa, Nepal</Mono>
				<Rise t={t} at={cue(1, 'glacier') - 0.1} text="A glacier collapsed." size={110} style={{marginTop: 24, maxWidth: 1100}} />
			</Abs>
			<Abs style={{right: 130, top: 300, textAlign: 'right'}}>
				{(['roads', 'bridges', 'phone'] as const).map((w, i) => {
					const k = prog(t, cue(1, w) - 0.1, 0.5, easeOut);
					const label = ['Roads', 'Bridges', 'Phone lines'][i];
					return (
						<div key={w} style={{position: 'relative', fontFamily: F.sans, fontWeight: 800, fontSize: 120, letterSpacing: '-0.05em', color: '#fff', opacity: k * (1 - prog(t, sceneStart(2) - 0.9, 0.4)), transform: `translateY(${(1 - k) * 40}px)`, lineHeight: 1.05}}>
							{label}
							<div style={{position: 'absolute', right: 0, top: '54%', height: 12, width: `${strike(w === 'phone' ? 'lines' : w) * 100}%`, background: C.red}} />
						</div>
					);
				})}
			</Abs>
		</AbsoluteFill>
	);
};

// ---------------- 02 three questions ----------------
const Questions: React.FC<{t: number}> = ({t}) => {
	const qs: [string, string][] = [
		['where', 'Where did the flood hit?'],
		['what', 'What was damaged?'],
		['who', 'Who is cut off?'],
	];
	return (
		<AbsoluteFill>
			<Abs style={{left: 150, top: 150}}>
				<Rise t={t} at={cue(2, 'rescuers') - 0.1} text="Rescuers needed three answers, fast." size={64} weight={600} color={C.ink} italicWords={['fast.']} />
			</Abs>
			<Abs style={{left: 150, top: 330}}>
				{qs.map(([w, q], i) => {
					const k = prog(t, cue(2, w) - 0.15, 0.6, easeOut);
					return (
						<div key={w} style={{display: 'flex', alignItems: 'baseline', gap: 36, marginBottom: 28, opacity: k, transform: `translateX(${(1 - k) * -40}px)`}}>
							<div style={{fontFamily: F.mono, fontSize: 30, color: C.orange}}>0{i + 1}</div>
							<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 118, letterSpacing: '-0.05em', color: C.ink}}>{q}</div>
						</div>
					);
				})}
			</Abs>
		</AbsoluteFill>
	);
};

// ---------------- 03 title ----------------
const Title: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const at = cue(2, 'water');
	const c = cam(t, {x: -1500, y: 1500, z: 0.05, rot: -8}, [{at, dur: 6, to: {z: 0.058, rot: 0}}]);
	return (
		<AbsoluteFill>
			<Raster c={c} src="corridor_hillshade.png" ext={d.cor.ext} opacity={0.35} filter="brightness(0.5) sepia(0.3) hue-rotate(180deg)" />
			<svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
				<g transform={tf(c)}>
					<path d={pathD(d.cor.path)} fill="none" stroke={C.orange} strokeOpacity={0.6} strokeWidth={6 / c.z} />
				</g>
			</svg>
			<Center>
				<div style={{display: 'flex', alignItems: 'baseline', transform: `scale(${lerp(1.08, 1, prog(t, at, 1.2, easeOut))})`, opacity: prog(t, at - 0.1, 0.4)}}>
					<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 230, letterSpacing: '-0.055em', color: '#fff'}}>WaterGuard</div>
					<div style={{width: 46, height: 46, borderRadius: 23, background: C.orange, marginLeft: 12}} />
				</div>
				<div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 64, color: 'rgba(255,255,255,.85)', opacity: prog(t, cue(2, 'space') - 0.2, 0.6), marginTop: -10}}>answers them from space.</div>
			</Center>
		</AbsoluteFill>
	);
};

// ---------------- 04 inputs + radar ----------------
const Inputs: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const cards: [string, number, string, string, string][] = [
		['Sentinel-1', cue(3, 'sentinel'), 'Radar · sees through cloud', 'ESA / Copernicus', C.waterSoft],
		['Sentinel-2', cue(3, 'sentinel', 1), 'Optical · where clear', 'ESA / Copernicus', C.green],
		['Copernicus DEM', cue(3, 'copernicus'), 'Elevation · 30 m', 'GLO-30', C.amber],
		['OpenStreetMap', cue(3, ['open', 'openstreetmap']), 'Snapshot 24 Aug 22:00 UTC', '0 edits after snapshot ✓', '#fff'],
	];
	const out = cue(3, 'radar', 1) - 0.2;
	const radarK = prog(t, out, 0.8);
	const c: Cam = {x: 0, y: 200, z: 0.15, rot: 0};
	const stackAt = cue(3, 'compare');
	const maskAt = cue(3, 'mask');
	const pre = ['29 JUN', '11 JUL', '23 JUL', '04 AUG', '16 AUG'];
	return (
		<AbsoluteFill>
			{/* input box + cards */}
			<AbsoluteFill style={{opacity: 1 - radarK}}>
				<Abs style={{left: 150, top: 150}}>
					<div style={{display: 'flex', gap: 20, opacity: prog(t, cue(3, 'area') - 0.2, 0.5)}}>
						<Pill bg="rgba(255,255,255,.08)" size={26} style={{border: '1px solid rgba(255,255,255,.2)', fontFamily: F.mono}}>
							▭ {typed(t, cue(3, 'area'), '85.313, 28.139 → 85.358, 28.198', 40)}
						</Pill>
						<Pill bg="rgba(255,106,43,.15)" color={C.orange} size={26} style={{border: `1px solid ${C.orange}`, fontFamily: F.mono, opacity: prog(t, cue(3, 'date') - 0.2, 0.4)}}>
							📅 {typed(t, cue(3, 'date'), '2026-08-25 22:00 UTC', 30)}
						</Pill>
					</div>
					<Rise t={t} at={cue(3, 'only') - 0.1} text="Only free data." size={96} style={{marginTop: 46}} italicWords={['free']} />
				</Abs>
				<Abs style={{left: 150, top: 560, display: 'flex', gap: 26}}>
					{cards.map(([name, at, l1, l2, col]) => {
						const k = prog(t, at - 0.1, 0.6, easeOut);
						return (
							<div key={name} style={{width: 380, padding: '28px 30px', borderRadius: 22, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', opacity: k, transform: `translateY(${(1 - k) * 40}px)`}}>
								<div style={{width: 14, height: 14, borderRadius: 7, background: col, marginBottom: 18}} />
								<div style={{fontFamily: F.sans, fontWeight: 700, fontSize: 40, color: '#fff', letterSpacing: '-0.03em'}}>{name}</div>
								<div style={{fontFamily: F.sans, fontSize: 24, color: 'rgba(255,255,255,.75)', marginTop: 8}}>{l1}</div>
								<Mono size={16} style={{marginTop: 14}} color={name === 'OpenStreetMap' ? C.green : 'rgba(255,255,255,.5)'}>
									{l2}
								</Mono>
							</div>
						);
					})}
				</Abs>
			</AbsoluteFill>
			{/* radar through cloud */}
			<AbsoluteFill style={{opacity: radarK}}>
				<Raster c={c} src="sya_s2_post.png" ext={d.sya.ext} opacity={0.35} filter="grayscale(1) brightness(.6)" />
				<Raster c={c} src="sya_sar_change.png" ext={d.sya.ext} opacity={prog(t, cue(3, 'sees'), 1.2)} pixelated />
				{/* monsoon cloud: drifting soft blobs that the radar ignores */}
				{Array.from({length: 9}).map((_, i) => {
					const x = ((i * 397 + t * 60) % 2400) - 300, y = 120 + ((i * 211) % 800);
					return <div key={i} style={{position: 'absolute', left: x, top: y, width: 520, height: 300, borderRadius: '50%', background: 'rgba(235,240,250,.55)', filter: 'blur(40px)', opacity: 0.9 - 0.6 * prog(t, cue(3, 'sees'), 1.5)}} />;
				})}
				<Abs style={{left: 120, top: 150}}>
					<Rise t={t} at={cue(3, 'radar', 1) - 0.1} text="Radar sees through monsoon cloud." size={78} italicWords={['through']} accent={{through: C.waterSoft}} />
				</Abs>
				{/* same-orbit stack */}
				<Abs style={{right: 140, top: 300}}>
					{pre.concat(['28 AUG']).map((dte, i) => {
						const k = prog(t, stackAt + i * 0.22, 0.5, easeOut);
						const post = i === 5;
						return (
							<div key={dte} style={{position: 'absolute', right: i * 46, top: i * 46, width: 340, height: 220, borderRadius: 14, overflow: 'hidden', border: `2px solid ${post ? C.orange : 'rgba(255,255,255,.35)'}`, opacity: k * (1 - prog(t, maskAt + 1.5, 0.5)), transform: `translateY(${(1 - k) * 60}px)`, boxShadow: lift(1, true), background: '#111'}}>
								<Img src={staticFile('data/sya_sar_change.png')} style={{width: '100%', height: '100%', objectFit: 'cover', filter: post ? 'none' : 'grayscale(1) brightness(.7)'}} />
								<div style={{position: 'absolute', left: 12, bottom: 10, fontFamily: F.mono, fontSize: 18, color: post ? C.orange : '#fff'}}>{post ? 'AFTER · ' : 'BEFORE · '}{dte}</div>
							</div>
						);
					})}
					<Mono size={18} style={{position: 'absolute', right: 0, top: 560, whiteSpace: 'nowrap', opacity: prog(t, cue(3, 'orbit'), 0.4)}}>Same orbit track 85 · ascending · 12-day repeat</Mono>
				</Abs>
				<Abs style={{left: 120, bottom: 130, opacity: prog(t, maskAt - 0.1, 0.5)}}>
					<Pill bg="rgba(255,255,255,.08)" size={26} style={{border: '1px dashed rgba(255,255,255,.5)'}}>
						▨ Layover &amp; shadow slopes masked, never guessed
					</Pill>
				</Abs>
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

// ---------------- 05-07 the Syapru Besi map: where, what, who ----------------
const SYA0: Cam = {x: -1700, y: 300, z: 0.21, rot: 0};
const Backdrop: React.FC<{src: string}> = ({src}) => (
	<AbsoluteFill>
		<Img src={staticFile(`data/${src}`)} style={{width: '100%', height: '100%', objectFit: 'cover', filter: 'blur(38px) brightness(.32) saturate(.8)', transform: 'scale(1.15)'}} />
	</AbsoluteFill>
);
const Syapru: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const s = d.sya;
	const syb = s.settlements.find((x) => x.name === 'Syabru Bensi')!;
	const c = cam(t, {...SYA0, z: 0.16}, [
		{at: sceneStart(4) - 0.4, dur: 3, to: {z: 0.21}},
		{at: cue(5, 'over'), dur: 2.5, to: {z: 0.28, x: -1000, y: 600}},
		{at: cue(6, 'then'), dur: 2, to: {z: 0.22, x: -1600, y: 300}},
		{at: cue(6, ['syabru', 'shabrubensi', 'siabru', 'sabru', 'bensi']) - 0.4, dur: 1.6, to: {x: syb.c[0] - 700, y: syb.c[1] + 100, z: 0.42}},
	]);
	const wipe = prog(t, cue(4, ['sentinel', 'sentinels']) - 0.3, 1.4);
	const impactK = prog(t, cue(4, 'impact') - 0.2, 0.9);
	const valley = win(t, cue(4, 'elevation'), cue(4, 'impact') + 0.2, 0.5, 0.4);
	const bK = prog(t, cue(5, ['map', 'mark']) - 0.2, 0.8);
	const hitK = prog(t, cue(5, '227') - 0.1, 0.9);
	const roadsCutK = prog(t, cue(5, '11') - 0.1, 1.0);
	const bridgeK = prog(t, cue(5, '8') - 0.1, 0.6, easeOut);
	const netK = prog(t, cue(6, 'road') - 0.1, 0.9);
	const removeK = prog(t, cue(6, 'remove'), 0.9);
	const bOut = 1 - 0.75 * prog(t, cue(6, 'then') - 0.3, 0.6);
	const fact = s.facts;
	const lay = (n: number) => (t >= sceneStart(n) - 0.5 ? 1 : 0);
	const textA = win(t, sceneStart(4) - 0.2, sceneStart(5) - 0.2, 0.4, 0.4);
	const textB = win(t, sceneStart(5), sceneStart(6) - 0.2, 0.4, 0.4);
	const textC = win(t, sceneStart(6), cue(6, 'downstream') - 0.3, 0.4, 0.4);
	return (
		<AbsoluteFill>
			<Backdrop src="sya_s2_post.png" />
			<Raster c={c} src="sya_s2_pre.png" ext={s.ext} filter={`brightness(${0.9 - 0.5 * lay(5)}) saturate(0.9)`} />
			<Raster c={c} src="sya_s2_post.png" ext={s.ext} clip={wipe} filter={`brightness(${0.95 - 0.5 * lay(5)})`} />
			{wipe > 0 && wipe < 1 && (() => {
				const [x0] = proj(c, [s.ext[0], 0]);
				const [x1] = proj(c, [s.ext[0] + s.ext[2], 0]);
				return <div style={{position: 'absolute', top: 0, bottom: 0, left: lerp(x0, x1, wipe) - 2, width: 4, background: '#fff', boxShadow: '0 0 20px #fff'}} />;
			})()}
			<Raster c={c} src="sya_impact.png" ext={s.ext} opacity={impactK * (1 - 0.45 * prog(t, cue(5, 'over'), 0.6))} pixelated />
			<svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
				<g transform={tf(c)}>
					{/* valley floor hint: draw the traced river line wide and soft */}
					{valley > 0 && s.path!.map((l, i) => <path key={i} d={pathD(l)} fill="none" stroke={C.amber} strokeOpacity={0.35 * valley} strokeWidth={420} strokeLinecap="round" strokeLinejoin="round" />)}
					{/* road network */}
					{netK > 0 &&
						s.roads!.map((r, i) => (
							<path key={i} d={pathD(r.l)} fill="none" stroke="#e8edf6" strokeOpacity={0.75 * netK} strokeWidth={(['primary', 'secondary', 'tertiary'].includes(r.h) ? 4 : 2) / c.z} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - netK} />
						))}
					{/* buildings */}
					{bK > 0 &&
						s.buildings!.map(([x, y, st, sz], i) => {
							const hit = st === 2 && hitK > (i % 97) / 97;
							const poss = st === 1 && hitK > 0.5;
							return <rect key={i} x={x - sz / 2} y={y - sz / 2} width={sz} height={sz} fill={hit ? C.red : poss ? C.amber : '#9aa3b2'} opacity={bK * bOut * (hit ? 1 : 0.8)} />;
						})}
					{/* roads inside impact */}
					{roadsCutK > 0 &&
						s.roads_cut!.map((l, i) => (
							<path key={i} d={pathD(l)} fill="none" stroke={C.red} strokeWidth={7 / c.z} strokeLinecap="round" pathLength={1} strokeDasharray={removeK > 0 ? `${0.08} ${0.06}` : '1 1'} strokeDashoffset={removeK > 0 ? -t * 0.3 : 1 - roadsCutK} opacity={1 - 0.7 * removeK} />
						))}
					{/* bridges */}
					{bridgeK > 0 &&
						s.bridges!.filter((b) => b.s === 'likely damaged').map((b, i) => {
							const k = clamp(bridgeK * 1.5 - i * 0.06);
							const r = (22 / c.z) * k;
							return (
								<g key={i} transform={`translate(${b.c[0]} ${b.c[1]})`} opacity={k}>
									<circle r={r * 1.3} fill="#0b0d11" opacity={0.7} />
									<path d={`M${-r},${-r}L${r},${r}M${r},${-r}L${-r},${r}`} stroke={C.red} strokeWidth={6 / c.z} strokeLinecap="round" />
								</g>
							);
						})}
					{/* settlements during "who" */}
					{netK > 0 &&
						s.settlements.map((x, i) => {
							const isCut = x.s === 'cut off';
							const k = prog(t, cue(6, 'town') + i * 0.04, 0.5);
							const red = isCut && removeK > 0.5;
							return <circle key={i} cx={x.c[0]} cy={x.c[1]} r={(10 + Math.min(x.b, 300) / 25) / c.z} fill={red ? C.red : x.s === 'connected' ? C.green : '#8a8f99'} stroke="#000" strokeWidth={2 / c.z} opacity={k} />;
						})}
				</g>
			</svg>
			<Tag c={c} p={syb.c} k={prog(t, cue(6, ['syabru', 'shabrubensi', 'siabru', 'sabru', 'bensi']) + 0.2, 0.6, easeOut) * (1 - prog(t, cue(6, 'downstream') - 0.4, 0.3))} dot={C.red}>
				Syabru Bensi · <span style={{color: C.red}}>{Math.round((syb.sh ?? 0) * 100)}% of {syb.b} buildings</span> · no road left
			</Tag>
			{/* left column text */}
			<AbsoluteFill style={{background: 'linear-gradient(90deg, rgba(11,13,17,.85) 0%, rgba(11,13,17,.0) 45%)', opacity: Math.max(textA, textB, textC)}} />
			<Abs style={{left: 120, top: 150, opacity: textA}}>
				<Mono size={20}>Syapru Besi · EMSR927 AOI01</Mono>
				<div style={{display: 'flex', gap: 14, marginTop: 20, opacity: prog(t, cue(4, 'sky') - 0.2, 0.4)}}>
					<Pill bg={wipe > 0.5 ? 'rgba(255,255,255,.1)' : '#fff'} color={wipe > 0.5 ? '#fff' : C.ink} size={22}>Before</Pill>
					<Pill bg={wipe > 0.5 ? '#fff' : 'rgba(255,255,255,.1)'} color={wipe > 0.5 ? C.ink : '#fff'} size={22}>After · Sentinel-2</Pill>
				</div>
				<Rise t={t} at={cue(4, 'stripped') - 0.1} text="Stripped forest. Fresh sediment." size={70} style={{marginTop: 30, maxWidth: 760}} />
				<div style={{marginTop: 30, opacity: valley}}>
					<Pill bg="rgba(255,191,46,.15)" color={C.amber} size={24} style={{border: `1px solid ${C.amber}`}}>
						Valley floor · ≤ 80 m above the river
					</Pill>
				</div>
				<div style={{marginTop: 40}}>
					<Stat t={t} at={cue(4, '174')} value={fact.impact.impact_ha} dec={1} unit="ha" label="flood + debris impact" color={C.orange} />
				</div>
			</Abs>
			<Abs style={{left: 120, top: 170, opacity: textB}}>
				<Mono size={20}>OpenStreetMap · the day before</Mono>
				<div style={{marginTop: 30}}>
					<Stat t={t} at={cue(5, '227')} value={fact.damage.buildings_likely_affected} label="buildings likely hit" color={C.red} />
					<Stat t={t} at={cue(5, '11')} value={fact.damage.road_km_in_impact} dec={1} unit="km" label="road inside the impact zone" />
					<Stat t={t} at={cue(5, '8')} value={fact.damage.bridges_likely_damaged} label="bridges likely gone" color={C.red} />
				</div>
			</Abs>
			<Abs style={{left: 120, top: 170, opacity: textC}}>
				<Rise t={t} at={cue(6, 'road') - 0.1} text="Who can still get out?" size={86} italicWords={['out?']} />
				<div style={{display: 'flex', flexDirection: 'column', gap: 14, marginTop: 36}}>
					{(['town', 'health', 'way'] as const).map((w, i) => (
						<div key={w} style={{opacity: prog(t, cue(6, w) - 0.1, 0.4)}}>
							<Pill bg="rgba(255,255,255,.08)" size={26} style={{border: '1px solid rgba(255,255,255,.2)'}}>
								{['🏘  A town', '✚  A health post', '↗  The road out'][i]}
							</Pill>
						</div>
					))}
				</div>
			</Abs>
		</AbsoluteFill>
	);
};

// ---------------- 07b Bidur: 15 settlements cut off ----------------
const Bidur: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const b = d.bid;
	const at = cue(6, 'downstream');
	const c = cam(t, {x: -5200, y: 0, z: 0.075, rot: 0}, [{at, dur: 5, to: {z: 0.085, x: -4600, y: 400}}]);
	const cut = b.settlements.filter((x) => x.s === 'cut off');
	return (
		<AbsoluteFill>
			<Backdrop src="bid_s2_post.png" />
			<Raster c={c} src="bid_s2_post.png" ext={b.ext} filter="brightness(.5)" />
			<Raster c={c} src="bid_impact.png" ext={b.ext} opacity={0.8} pixelated />
			<svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
				<g transform={tf(c)}>
					{b.settlements.map((x, i) => {
						const isCut = x.s === 'cut off';
						const k = prog(t, at + 0.3 + (i % 40) * 0.02, 0.4);
						const red = (isCut || (x as any).sh >= 0.5) && t > cue(6, ['eleven', '11', '11000', '15']) - 0.2;
						return <circle key={i} cx={x.c[0]} cy={x.c[1]} r={(red ? 14 : 7) / c.z} fill={red ? C.red : x.s === 'partly cut' ? C.amber : x.s === 'connected' ? C.green : '#777'} stroke="#000" strokeWidth={1.5 / c.z} opacity={k * (red ? 1 : 0.6)} />;
					})}
				</g>
			</svg>
			<AbsoluteFill style={{background: 'linear-gradient(90deg, rgba(11,13,17,.85) 0%, rgba(11,13,17,0) 45%)'}} />
			<Abs style={{left: 120, top: 170}}>
				<Mono size={20}>Downstream · Bidur · EMSR927 AOI03</Mono>
				<div style={{marginTop: 30}}>
					<Stat t={t} at={cue(6, ['eleven', '11', '11000', '15'])} value={b.facts.access.people_est_stranded_vehicle} label="people with no road left (estimate)" color={C.red} size={170} />
				</div>
				<div style={{opacity: prog(t, cue(6, ['eleven', '11', '11000', '15']) + 0.6, 0.5), marginTop: 10}}>
					{(b.stranded ?? []).filter((x) => !x.name.startsWith('unnamed')).slice(0, 3).map((x) => (
						<Mono key={x.name} size={20} style={{marginBottom: 8}} color="rgba(255,255,255,.75)">
							{x.name} · {Math.round(x.sh * 100)}% of buildings
						</Mono>
					))}
				</div>
			</Abs>
		</AbsoluteFill>
	);
};

// ---------------- 08 copilot ----------------
const DEV = (s: string) => s.replace(/[0-9]/g, (x) => '०१२३४५६७८९'[+x]);
const Copilot: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const s = sceneStart(7);
	const q = 'स्याब्रुबेसीको अवस्था के छ?';
	const qAt = cue(7, 'nepali') - 0.4;
	const toolAt = cue(7, ['reads', 'treats']);
	const ansAt = cue(7, 'tools') + 0.4;
	const verAt = cue(7, 'verifier');
	const syb = d.sya.settlements.find((x) => x.name === 'Syabru Bensi')!;
	const pct = String(Math.round((syb.sh ?? 0) * 100));
	const ans = `स्याब्रुबेसी: ${DEV(String(syb.b))} घर। तीमध्ये ${DEV(pct)}% घरको सडक सम्पर्क टुटेको छ।`;
	const repAt = cue(7, 'click');
	const pathAt = cue(7, 'upstream');
	const phoneOut = prog(t, repAt - 0.2, 0.6);
	const nums = [DEV(String(syb.b)), DEV(pct)];
	return (
		<AbsoluteFill>
			<Abs style={{left: 140, top: 170, opacity: 1 - phoneOut}}>
				<div style={{display: 'flex', gap: 12, opacity: prog(t, s, 0.5)}}>
					<Pill bg={t < qAt ? C.ink : 'rgba(0,0,0,.08)'} color={t < qAt ? '#fff' : C.ink} size={24}>English</Pill>
					<Pill bg={t >= qAt ? C.ink : 'rgba(0,0,0,.08)'} color={t >= qAt ? '#fff' : C.ink} size={24}>नेपाली</Pill>
				</div>
				<Rise t={t} at={cue(7, ['copilot', 'co']) - 0.1} text="No numbers of its own." size={92} color={C.ink} style={{marginTop: 40, maxWidth: 820}} italicWords={['own.']} />
				<div style={{marginTop: 40, display: 'flex', flexDirection: 'column', gap: 16, width: 760}}>
					<Tool t={t} at={toolAt} done={toolAt + 0.7} label="find_settlement()" detail="→ Syabru Bensi" dark={false} />
					<Tool t={t} at={verAt - 0.1} done={cue(7, 'shown')} label="verify()" detail={`2 numbers · found in tool results`} dark={false} />
				</div>
			</Abs>
			<Phone x={1380} y={560} light style={{opacity: 1 - phoneOut, transform: `translateY(${phoneOut * 200}px)`}}>
				<div style={{padding: '90px 28px 0', fontFamily: F.sans}}>
					<div style={{fontWeight: 700, fontSize: 24, color: C.ink, marginBottom: 24}}>
						<span style={{color: C.orange}}>◉</span> WaterGuard copilot
					</div>
					{t > qAt && (
						<div style={{marginLeft: 'auto', maxWidth: 320, background: C.water, color: '#fff', padding: '14px 18px', borderRadius: '20px 20px 4px 20px', fontFamily: F.deva, fontSize: 25, fontWeight: 500}}>
							{typed(t, qAt, q, 22)}
						</div>
					)}
					{t > ansAt && (
						<div style={{marginTop: 22, maxWidth: 340, background: '#fff', border: '1px solid rgba(0,0,0,.08)', color: C.ink, padding: '16px 18px', borderRadius: '20px 20px 20px 4px', fontFamily: F.deva, fontSize: 25, lineHeight: 1.5, boxShadow: lift(0.4)}}>
							{(() => {
								const txt = typed(t, ansAt, ans, 30);
								const parts = txt.split(new RegExp(`(${nums.join('|')})`));
								const vk = prog(t, verAt + 0.3, 0.4);
								return parts.map((p, i) =>
									nums.includes(p) ? (
										<span key={i} style={{background: `rgba(31,209,122,${0.25 * vk})`, borderRadius: 6, padding: '0 4px', fontWeight: 700}}>
											{p}
											{vk > 0.5 && <span style={{color: C.green, fontSize: 18, marginLeft: 3}}>✓</span>}
										</span>
									) : (
										<span key={i}>{p}</span>
									),
								);
							})()}
							<div style={{marginTop: 12, fontFamily: F.mono, fontSize: 15, color: C.green, opacity: prog(t, cue(7, 'shown'), 0.4)}}>✓ 2 numbers checked against the maps</div>
						</div>
					)}
				</div>
			</Phone>
			{/* one-page report */}
			{phoneOut > 0 && (
				<Abs style={{left: 0, right: 0, top: 0, bottom: 0, opacity: 1 - prog(t, pathAt - 0.3, 0.4)}}>
					<div style={{position: 'absolute', left: 1040, top: 90 + (1 - prog(t, repAt, 0.8, easeOut)) * 900, width: 640, height: 900, background: '#fff', borderRadius: 10, overflow: 'hidden', boxShadow: lift(1), transform: 'rotate(2deg)'}}>
						<Img src={staticFile('data/sitrep_en.png')} style={{width: '100%', objectFit: 'cover', objectPosition: 'top'}} />
					</div>
					<Abs style={{left: 140, top: 300}}>
						<Rise t={t} at={repAt} text="One click. One page." size={104} color={C.ink} italicWords={['page.']} />
						<Mono size={22} color="rgba(10,12,16,.6)" style={{marginTop: 26, opacity: prog(t, repAt + 0.8, 0.4)}}>
							English · नेपाली · every number from the maps
						</Mono>
					</Abs>
				</Abs>
			)}
		</AbsoluteFill>
	);
};

// flood path from upstream, on the corridor
const FloodPath: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const at = cue(7, 'upstream') - 0.3;
	const cor = d.cor;
	const c = cam(t, {x: 1800, y: -4500, z: 0.075, rot: 0}, [{at, dur: 4, to: {x: -2500, y: 3000, z: 0.06}}]);
	const draw = prog(t, at + 0.5, 3.2, (x) => x);
	const n = Math.max(2, Math.floor(cor.path.length * draw));
	return (
		<AbsoluteFill>
			<Raster c={c} src="corridor_hillshade.png" ext={cor.ext} filter="brightness(.6) sepia(.3) hue-rotate(180deg)" />
			<svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
				<g transform={tf(c)}>
					<path d={pathD(cor.path.slice(0, n))} fill="none" stroke="#00e5ff" strokeWidth={8 / c.z} strokeDasharray={`${18 / c.z} ${12 / c.z}`} strokeLinecap="round" />
				</g>
			</svg>
			{cor.places.map((p, i) => {
				const idx = cor.path.reduce((b, q, j) => (Math.hypot(q[0] - p.c[0], q[1] - p.c[1]) < Math.hypot(cor.path[b][0] - p.c[0], cor.path[b][1] - p.c[1]) ? j : b), 0);
				return (
					<Tag key={i} c={c} p={p.c} k={n > idx ? prog(t, at + 0.5 + (idx / cor.path.length) * 3.2, 0.4) : 0} dot="#00e5ff">
						{p.name}
					</Tag>
				);
			})}
			<Abs style={{left: 120, top: 150}}>
				<Rise t={t} at={at + 0.2} text="Trace the flood path." size={90} italicWords={['path.']} accent={{'path.': '#00e5ff'}} />
				<Mono size={20} style={{marginTop: 20, opacity: prog(t, at + 1, 0.4)}}>Copernicus DEM · D8 flow · 70 km · Timure → Bidur</Mono>
			</Abs>
		</AbsoluteFill>
	);
};

// ---------------- 09 validation ----------------
const Validation: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const s = sceneStart(8);
	const rows = d.val.filter((r: any) => r.aoi);
	const held = rows.filter((r: any) => r.split === 'held-out');
	const imgK = prog(t, cue(8, 'copernicus') - 0.2, 0.8, easeOut);
	const fakeAt = cue(8, 'fake');
	return (
		<AbsoluteFill>
			<Abs style={{right: 120, top: 120, width: 520, height: 860, borderRadius: 16, overflow: 'hidden', opacity: imgK, transform: `translateX(${(1 - imgK) * 80}px)`, boxShadow: lift(1, true)}}>
				<Img src={staticFile('data/val_bidur.png')} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
			</Abs>
			<Abs style={{right: 120, top: 990, width: 520, opacity: imgK}}>
				<Mono size={15} color="rgba(255,255,255,.6)">
					<span style={{color: C.green}}>■</span> both &nbsp; <span style={{color: '#ff8c28'}}>■</span> only us &nbsp; <span style={{color: '#3c78ff'}}>■</span> only Copernicus EMS
				</Mono>
			</Abs>
			<Abs style={{left: 120, top: 140}}>
				<Mono size={20} style={{opacity: prog(t, s, 0.4)}}>Checked against Copernicus EMS · EMSR927</Mono>
				<Rise t={t} at={cue(8, 'never') - 0.3} text="Two valleys we never tuned on." size={62} weight={600} style={{marginTop: 22}} italicWords={['never']} />
				<div style={{display: 'flex', gap: 70, marginTop: 40}}>
					{held.map((r: any, i: number) => {
						const at = cue(8, i === 0 ? '0' : '0', i);
						const k = prog(t, at - 0.15, 0.6, easeOut);
						return (
							<div key={r.aoi} style={{opacity: k, transform: `translateY(${(1 - k) * 30}px)`}}>
								<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 170, letterSpacing: '-0.05em', color: '#fff', lineHeight: 0.95}}>{count(t, at, 0.9, r.area.f1).toFixed(2)}</div>
								<Mono size={20} style={{marginTop: 8}}>F1 · {r.name}</Mono>
							</div>
						);
					})}
				</div>
				<div style={{marginTop: 60, opacity: prog(t, cue(8, 'buildings') - 0.2, 0.5)}}>
					<div style={{display: 'flex', gap: 60}}>
						{held.map((r: any) => {
							const [a, b] = r.buildings.by_grade.Destroyed.split('/').map(Number);
							return (
								<div key={r.aoi}>
									<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 110, letterSpacing: '-0.05em', color: C.green, lineHeight: 1}}>
										{((a / b) * 100).toFixed(a / b > 0.99 ? 1 : 0)}
										<span style={{fontSize: 56}}>%</span>
									</div>
									<Mono size={16} style={{marginTop: 6}}>{r.name} · {a}/{b}</Mono>
								</div>
							);
						})}
					</div>
					<Mono size={20} style={{marginTop: 14}}>of buildings EMS rated destroyed fall inside our map</Mono>
				</div>
				<div style={{display: 'flex', gap: 16, marginTop: 50}}>
					{['Placebo date · 0 ha', 'Untouched valley · 0 ha'].map((x, i) => (
						<div key={x} style={{opacity: prog(t, fakeAt - 0.1 + i * 0.9, 0.4)}}>
							<Pill bg="rgba(31,209,122,.12)" color={C.green} size={26} style={{border: `1px solid ${C.green}`}}>
								✓ {x}
							</Pill>
						</div>
					))}
				</div>
			</Abs>
		</AbsoluteFill>
	);
};

// ---------------- 10 limits + end ----------------
const End: React.FC<{t: number; d: Data}> = ({t, d}) => {
	const s = sceneStart(9);
	const but = cue(9, 'but');
	const endAt = cue(9, 'water', 1);
	const c = cam(t, {x: -1500, y: 1000, z: 0.05, rot: 4}, [{at: s, dur: 10, to: {z: 0.06, rot: 0}}]);
	const endK = prog(t, endAt - 0.2, 0.8, easeOut);
	// orbit sweep: a satellite ground track crossing every few seconds
	const sweep = ((t - s) / 2.6) % 1;
	return (
		<AbsoluteFill>
			<Raster c={c} src="corridor_hillshade.png" ext={d.cor.ext} opacity={0.4 * (1 - 0.6 * endK)} filter="brightness(.5) sepia(.3) hue-rotate(180deg)" />
			<div style={{position: 'absolute', top: 0, bottom: 0, left: lerp(-300, W + 300, sweep), width: 260, background: 'linear-gradient(90deg, rgba(122,162,255,0), rgba(122,162,255,.18), rgba(122,162,255,0))', transform: 'skewX(-14deg)', opacity: 1 - endK}} />
			<Abs style={{left: 150, top: 300, opacity: 1 - prog(t, but - 0.3, 0.4)}}>
				<Rise t={t} at={s - 0.1} text="Satellites pass every few days." size={92} />
				<Rise t={t} at={cue(9, 'cannot') - 0.1} text="WaterGuard cannot warn." size={92} italicWords={['warn.']} accent={{'warn.': C.amber}} />
				<Mono size={20} style={{marginTop: 30, opacity: prog(t, cue(9, 'warn'), 0.4)}}>It maps damage after the fact · first radar look here: +2.6 days</Mono>
			</Abs>
			<Abs style={{left: 150, top: 300, opacity: win(t, but - 0.1, endAt - 0.3, 0.4, 0.4)}}>
				<Rise t={t} at={but} text="When the next valley goes dark," size={80} weight={600} color="rgba(255,255,255,.85)" />
				<Rise t={t} at={cue(9, 'rescuers') - 0.1} text="rescuers will know where to go first." size={110} italicWords={['first.']} accent={{'first.': C.orange}} style={{maxWidth: 1600}} />
			</Abs>
			{endK > 0 && (
				<Center>
					<div style={{display: 'flex', alignItems: 'baseline', transform: `scale(${lerp(0.92, 1, endK)})`, opacity: endK}}>
						<div style={{fontFamily: F.sans, fontWeight: 800, fontSize: 210, letterSpacing: '-0.055em', color: '#fff'}}>WaterGuard</div>
						<div style={{width: 44, height: 44, borderRadius: 22, background: C.orange, marginLeft: 12}} />
					</div>
					<div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 56, color: 'rgba(255,255,255,.85)', opacity: prog(t, endAt + 0.5, 0.6), marginTop: -6}}>Flood damage, from space.</div>
					<div style={{display: 'flex', gap: 16, marginTop: 50, opacity: prog(t, endAt + 1.0, 0.6)}}>
						<Pill bg="#fff" color={C.ink} size={26}>Flood damage from space</Pill>
						<Pill bg="rgba(255,255,255,.1)" size={26}>Sentinel-1 · Sentinel-2 · Copernicus DEM · OSM</Pill>
					</div>
					<Mono size={15} style={{marginTop: 40, opacity: prog(t, endAt + 1.4, 0.6), textAlign: 'center', lineHeight: 1.7}} color="rgba(255,255,255,.45)">
						Contains modified Copernicus Sentinel data 2026 · Copernicus WorldDEM-30 © DLR e.V. 2010–2014, © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the EU and ESA
						<br />© OpenStreetMap contributors · Validation only: European Union, Copernicus Emergency Management Service data · Educational prototype, not an operational tool
					</Mono>
				</Center>
			)}
		</AbsoluteFill>
	);
};

// ---------------- the film ----------------
export const Film: React.FC = () => {
	const frame = useCurrentFrame();
	const t = frame / FPS;
	const [d, setD] = useState<Data | null>(getData());
	const [h] = useState(() => (getData() ? null : delayRender('film-data')));
	useEffect(() => {
		if (d) return;
		useDataOnce().then((x) => {
			setD(x);
			if (h !== null) continueRender(h);
		});
	}, [d, h]);
	if (!d) return <AbsoluteFill style={{background: C.ink}} />;

	const layers: Layer[] = [
		{from: -1, bg: C.ink, dark: true, o: [960, 540], render: (tt, dd) => <Night t={tt} d={dd} />},
		{from: sceneStart(2) - 0.5, bg: C.paper, dark: false, o: [960, 540], render: (tt) => <Questions t={tt} />},
		{from: cue(2, 'water') - 0.1, bg: C.ink, dark: true, o: [960, 540], dur: 0.7, render: (tt, dd) => <Title t={tt} d={dd} />},
		{from: sceneStart(3) - 0.4, bg: C.ink2, dark: true, o: [300, 200], render: (tt, dd) => <Inputs t={tt} d={dd} />},
		{from: sceneStart(4) - 0.5, bg: C.ink, dark: true, o: [960, 540], render: (tt, dd) => <Syapru t={tt} d={dd} />},
		{from: cue(6, 'downstream') - 0.2, bg: C.ink, dark: true, o: [960, 900], render: (tt, dd) => <Bidur t={tt} d={dd} />},
		{from: sceneStart(7) - 0.5, bg: C.paper, dark: false, o: [1380, 560], render: (tt, dd) => <Copilot t={tt} d={dd} />},
		{from: cue(7, 'upstream') - 0.4, bg: C.ink, dark: true, o: [960, 200], render: (tt, dd) => <FloodPath t={tt} d={dd} />},
		{from: sceneStart(8) - 0.5, bg: C.ink, dark: true, o: [960, 540], render: (tt, dd) => <Validation t={tt} d={dd} />},
		{from: sceneStart(9) - 0.5, bg: C.ink, dark: true, o: [960, 560], render: (tt, dd) => <End t={tt} d={dd} />},
	];
	let cur = 0;
	layers.forEach((L, i) => {
		if (t >= L.from) cur = i;
	});
	const covering = prog(t, layers[cur].from, layers[cur].dur ?? 0.8) < 1;
	const visible = covering && cur > 0 ? [cur - 1, cur] : [cur];
	const chapters = [
		{t: sceneStart(1), label: '01 — The night'},
		{t: sceneStart(2), label: '02 — Three questions'},
		{t: sceneStart(3), label: '03 — Free data'},
		{t: sceneStart(4), label: '04 — Where it hit'},
		{t: sceneStart(5), label: '05 — What was damaged'},
		{t: sceneStart(6), label: '06 — Who is cut off'},
		{t: sceneStart(7), label: '07 — Copilot'},
		{t: sceneStart(8), label: '08 — Checked'},
		{t: sceneStart(9), label: '09 — Limits'},
	];
	const ch = [...chapters].reverse().find((c) => t >= c.t - 0.3)?.label ?? '00 — Cold open';
	return (
		<AbsoluteFill style={{background: C.ink}}>
			{visible.map((i) => (
				<Reveal key={i} t={t} L={layers[i]}>
					{layers[i].render(t, d)}
				</Reveal>
			))}
			<HUD t={t} end={END} dark={layers[cur].dark ? 1 : 0} chapter={ch} chapters={chapters} opacity={prog(t, 0.2, 0.8) * (1 - prog(t, END - 2.2, 0.8))} />
		</AbsoluteFill>
	);
};
