// The product window: real dashboard stills (2x), crossfaded state to state, a camera that glides to
// any recorded element box, and a pointer that travels between recorded click targets.
import React from 'react';
import {Img, staticFile} from 'remotion';
import {C, clamp, ease, easeOut, F, lerp} from '../lib';
import {Cursor} from '../ui';
import {Box} from './plib';

// one grid for the whole film: headline column on the left, window on the right
export const FRAME = {x: 500, y: 150, w: 1340, bar: 38};
export const CSS = {w: 1600, h: 900};
export const S0 = FRAME.w / CSS.w;            // css px -> screen px at zoom 1
export const FH = CSS.h * S0;                 // window content height

export type StateKey = {t: number; s: string};
export type CamKey = {t: number; dur?: number; box?: Box | null; z?: number};   // box in css px; none = whole page
export type CurKey = {t: number; p: [number, number]; click?: boolean; dur?: number};

const center = (b: Box): [number, number] => [b[0] + b[2] / 2, b[1] + b[3] / 2];

/** camera at time t: centre (css px) and zoom, eased between keys */
export const camAt = (t: number, keys: CamKey[]) => {
	const resolve = (k: CamKey) => {
		if (!k.box) return {c: [CSS.w / 2, CSS.h / 2] as [number, number], z: 1};
		const z = k.z ?? clamp(Math.min(CSS.w / (k.box[2] * 1.35), CSS.h / (k.box[3] * 1.35)), 1, 2.3);
		const [cx, cy] = center(k.box);
		// keep the view inside the page
		const hw = CSS.w / 2 / z, hh = CSS.h / 2 / z;
		return {c: [clamp(cx, hw, CSS.w - hw), clamp(cy, hh, CSS.h - hh)] as [number, number], z};
	};
	let cur = resolve(keys[0]);
	for (let i = 1; i < keys.length; i++) {
		const k = keys[i];
		const g = resolve(k);
		const p = ease(clamp((t - k.t) / (k.dur ?? 1.1)));
		if (p <= 0) break;
		cur = {c: [lerp(cur.c[0], g.c[0], p), lerp(cur.c[1], g.c[1], p)], z: Math.exp(lerp(Math.log(cur.z), Math.log(g.z), p))};
	}
	return cur;
};

/** css px -> screen px through the camera */
export const toScreen = (p: [number, number], cam: {c: [number, number]; z: number}): [number, number] => [
	FRAME.x + ((p[0] - cam.c[0]) * cam.z + CSS.w / 2) * S0,
	FRAME.y + FRAME.bar + ((p[1] - cam.c[1]) * cam.z + CSS.h / 2) * S0,
];

export const curAt = (t: number, keys: CurKey[]): {p: [number, number]; press: number; visible: number} => {
	if (!keys.length || t < keys[0].t - 0.4) return {p: [CSS.w * 0.6, CSS.h * 1.1], press: 0, visible: 0};
	let p = keys[0].p;
	for (let i = 1; i < keys.length; i++) {
		const k = keys[i];
		const dur = k.dur ?? 0.75;
		const q = ease(clamp((t - (k.t - dur)) / dur));     // arrive exactly at k.t
		if (q <= 0) break;
		// a gentle arc instead of a straight line
		const a = keys[i - 1].p, b = k.p;
		const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - Math.hypot(b[0] - a[0], b[1] - a[1]) * 0.12];
		const u = q;
		p = [
			(1 - u) * (1 - u) * a[0] + 2 * (1 - u) * u * mid[0] + u * u * b[0],
			(1 - u) * (1 - u) * a[1] + 2 * (1 - u) * u * mid[1] + u * u * b[1],
		];
	}
	const press = Math.max(0, ...keys.filter((k) => k.click).map((k) => 1 - Math.abs(t - k.t) / 0.12)) ;
	return {p, press: clamp(press), visible: clamp((t - (keys[0].t - 0.4)) / 0.4)};
};

export const boxCenter = (b: Box | null | undefined, dx = 0, dy = 0): [number, number] =>
	b ? [b[0] + b[2] / 2 + dx, b[1] + b[3] / 2 + dy] : [CSS.w / 2, CSS.h / 2];

/** Browser window with crossfaded states, camera, pointer, click ripples. */
export const Screen: React.FC<{
	t: number;
	states: StateKey[];
	cam: CamKey[];
	cursor?: CurKey[];
	enter: number;             // 0..1 window presence (scale + fade)
	url?: string;
	overlay?: (cam: {c: [number, number]; z: number}) => React.ReactNode;   // drawn above the page, below the pointer
}> = ({t, states, cam, cursor = [], enter, url = 'd1sgb39rsg0dlm.cloudfront.net', overlay}) => {
	if (enter <= 0) return null;
	const c = camAt(t, cam);
	// current + previous state, crossfade 0.45 s
	let i = 0;
	for (let k = 0; k < states.length; k++) if (t >= states[k].t) i = k;
	const cur = states[i], prev = states[i - 1];
	const fade = prev ? easeOut(clamp((t - cur.t) / 0.45)) : 1;
	const page = (s: string, o: number) => (
		<Img
			src={staticFile(`ui/${s}.png`)}
			style={{position: 'absolute', left: 0, top: 0, width: CSS.w, height: CSS.h, opacity: o}}
		/>
	);
	const K = easeOut(enter);
	const cu = curAt(t, cursor);
	const sp = toScreen(cu.p, c);
	const clicks = cursor.filter((k) => k.click && t >= k.t && t < k.t + 0.6);
	return (
		<>
			<div
				style={{
					position: 'absolute', left: FRAME.x, top: FRAME.y, width: FRAME.w, height: FRAME.bar + FH,
					borderRadius: 18, overflow: 'hidden', background: '#121211',
					boxShadow: '0 2px 6px rgba(0,0,0,.35), 0 30px 80px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.08)',
					opacity: K, transform: `translateY(${(1 - K) * 40}px) scale(${0.96 + 0.04 * K})`, transformOrigin: '50% 60%',
				}}
			>
				<div style={{height: FRAME.bar, background: '#1b1b1a', display: 'flex', alignItems: 'center', gap: 9, padding: '0 16px', borderBottom: '1px solid rgba(255,255,255,.06)'}}>
					{['#ff5f57', '#febc2e', '#28c840'].map((col) => <div key={col} style={{width: 12, height: 12, borderRadius: 6, background: col, opacity: 0.9}} />)}
					<div style={{marginLeft: 18, flex: 1, height: 24, borderRadius: 7, background: 'rgba(255,255,255,.06)', display: 'flex', alignItems: 'center', padding: '0 12px', fontFamily: F.mono, fontSize: 14, color: 'rgba(255,255,255,.55)', letterSpacing: '0.02em'}}>
						<span style={{color: C.green, marginRight: 8}}>●</span>https://{url}
					</div>
				</div>
				<div style={{position: 'relative', width: FRAME.w, height: FH, overflow: 'hidden'}}>
					<div style={{position: 'absolute', left: 0, top: 0, width: CSS.w, height: CSS.h, transformOrigin: '0 0',
						transform: `scale(${S0}) translate(${CSS.w / 2}px, ${CSS.h / 2}px) scale(${c.z}) translate(${-c.c[0]}px, ${-c.c[1]}px)`}}>
						{prev && fade < 1 && page(prev.s, 1)}
						{page(cur.s, fade)}
					</div>
				</div>
			</div>
			{overlay && <div style={{position: 'absolute', inset: 0, opacity: K}}>{overlay(c)}</div>}
			{clicks.map((k, j) => {
				const q = clamp((t - k.t) / 0.6);
				const [x, y] = toScreen(k.p, c);
				const r = 8 + easeOut(q) * 34;
				return <div key={j} style={{position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: '50%', border: `2px solid ${C.orange}`, opacity: (1 - q) * K}} />;
			})}
			{cursor.length > 0 && <Cursor x={sp[0]} y={sp[1]} press={cu.press} opacity={cu.visible * K} />}
		</>
	);
};

/** highlight ring around a css-px box, drawn in screen space */
export const Focus: React.FC<{b: Box | null | undefined; cam: {c: [number, number]; z: number}; k: number; color?: string; pad?: number; label?: string}> = ({b, cam, k, color = C.orange, pad = 6, label}) => {
	if (!b || k <= 0) return null;
	const [x0, y0] = toScreen([b[0] - pad, b[1] - pad], cam);
	const [x1, y1] = toScreen([b[0] + b[2] + pad, b[1] + b[3] + pad], cam);
	const q = easeOut(clamp(k));
	return (
		<>
			<div style={{position: 'absolute', left: x0, top: y0, width: x1 - x0, height: y1 - y0, borderRadius: 12, border: `3px solid ${color}`,
				boxShadow: `0 0 0 ${8 * (1 - q)}px ${color}33, 0 0 30px ${color}55`, opacity: q, transform: `scale(${1.04 - 0.04 * q})`}} />
			{label && (
				<div style={{position: 'absolute', left: x0, top: y0 - 46, opacity: q, transform: `translateY(${(1 - q) * 10}px)`, background: color, color: '#111',
					fontFamily: F.mono, fontSize: 18, fontWeight: 500, padding: '6px 12px', borderRadius: 8, letterSpacing: '0.04em', whiteSpace: 'nowrap'}}>{label}</div>
			)}
		</>
	);
};
