// Small motion primitives: masked word rises, counters, HUD frame, cursor, phone, chips.
import React from 'react';
import {C, clamp, ease, easeOut, F, H, lerp, prog, W} from './lib';

export const Abs: React.FC<{style?: React.CSSProperties; children?: React.ReactNode}> = ({style, children}) => (
	<div style={{position: 'absolute', ...style}}>{children}</div>
);

/** Words rise out of a mask one after another. `at` = start (s), `stagger` per word. */
export const Rise: React.FC<{
	t: number;
	at: number;
	text: string;
	out?: number; // time to exit (words fall away)
	stagger?: number;
	size: number;
	color?: string;
	weight?: number;
	font?: string;
	tracking?: number;
	style?: React.CSSProperties;
	italicWords?: string[];
	accent?: Record<string, string>;
}> = ({t, at, text, out, stagger = 0.06, size, color = '#fff', weight = 800, font = F.sans, tracking = -0.045, style, italicWords = [], accent = {}}) => {
	const words = text.split(' ');
	return (
		<div style={{display: 'flex', flexWrap: 'wrap', gap: `0 ${size * 0.24}px`, fontSize: size, lineHeight: 1.0, ...style}}>
			{words.map((w, i) => {
				const k = prog(t, at + i * stagger, 0.7, easeOut);
				const o = out !== undefined ? prog(t, out + i * stagger * 0.5, 0.5, ease) : 0;
				const it = italicWords.includes(w);
				return (
					<span key={i} style={{display: 'inline-block', overflow: 'hidden', paddingBottom: size * 0.12, marginBottom: -size * 0.12}}>
						<span
							style={{
								display: 'inline-block',
								transform: `translateY(${(1 - k) * 105 - o * 105}%)`,
								color: accent[w] ?? color,
								fontWeight: it ? 400 : weight,
								fontFamily: it ? F.serif : font,
								fontStyle: it ? 'italic' : 'normal',
								letterSpacing: it ? '-0.01em' : `${tracking}em`,
							}}
						>
							{w}
						</span>
					</span>
				);
			})}
		</div>
	);
};

export const fmt = (v: number, dec = 0) =>
	v.toLocaleString('en-US', {minimumFractionDigits: dec, maximumFractionDigits: dec});

/** counts from 0 to `to` between at..at+dur */
export const count = (t: number, at: number, dur: number, to: number, from = 0) => lerp(from, to, easeOut(clamp((t - at) / dur)));

/** Typewriter: visible prefix of text */
export const typed = (t: number, at: number, text: string, cps = 26) => text.slice(0, Math.max(0, Math.floor((t - at) * cps)));

/** macOS-style pointer */
export const Cursor: React.FC<{x: number; y: number; press?: number; opacity?: number}> = ({x, y, press = 0, opacity = 1}) => (
	<svg
		width={34}
		height={46}
		viewBox="0 0 17 23"
		style={{position: 'absolute', left: x - 3, top: y - 2, opacity, transform: `scale(${1 - press * 0.12})`, transformOrigin: '3px 2px', filter: 'drop-shadow(0 3px 6px rgba(0,0,0,.35))', zIndex: 50}}
	>
		<path d="M1 1 L1 18 L5.2 14 L8 21 L11 19.7 L8.3 13 L14 13 Z" fill="#000" stroke="#fff" strokeWidth="1.3" strokeLinejoin="round" />
	</svg>
);

/** click ripple ring */
export const Ripple: React.FC<{t: number; at: number; x: number; y: number; color?: string}> = ({t, at, x, y, color = '#fff'}) => {
	const k = clamp((t - at) / 0.6);
	if (k <= 0 || k >= 1) return null;
	const r = 10 + easeOut(k) * 60;
	return <div style={{position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: '50%', border: `2px solid ${color}`, opacity: 1 - k}} />;
};

/** HUD frame: corner labels, timecode, chapter, progress ticks */
export const HUD: React.FC<{t: number; end: number; dark: number; chapter: string; chapters: {t: number; label: string}[]; opacity: number}> = ({t, end, dark, chapter, chapters, opacity}) => {
	const col = dark > 0.5 ? 'rgba(255,255,255,0.55)' : 'rgba(10,12,16,0.55)';
	const line = dark > 0.5 ? 'rgba(255,255,255,0.18)' : 'rgba(10,12,16,0.15)';
	const mm = Math.floor(t / 60), ss = (t % 60).toFixed(2).padStart(5, '0');
	const st: React.CSSProperties = {position: 'absolute', fontFamily: F.mono, fontSize: 15, letterSpacing: '0.08em', color: col, textTransform: 'uppercase'};
	return (
		<div style={{position: 'absolute', inset: 0, opacity, pointerEvents: 'none', zIndex: 80}}>
			<div style={{...st, left: 48, top: 36}}>
				<span style={{color: C.orange}}>●</span>&nbsp; WaterGuard film
			</div>
			<div style={{...st, right: 48, top: 36}}>T+{String(mm).padStart(2, '0')}:{ss}</div>
			<div style={{...st, left: 48, bottom: 58}}>{chapter}</div>
			<div style={{...st, right: 48, bottom: 58}}>Trishuli corridor · 28.16°N 85.34°E · EMSR927</div>
			<div style={{position: 'absolute', left: 48, right: 48, bottom: 40, height: 1, background: line}} />
			<div style={{position: 'absolute', left: 48, bottom: 40, height: 2, width: (W - 96) * (t / end), background: dark > 0.5 ? '#fff' : C.ink, marginBottom: -0.5}} />
			{chapters.map((c, i) => (
				<div key={i} style={{position: 'absolute', left: 48 + (W - 96) * (c.t / end) - 3, bottom: 37, width: 7, height: 7, transform: 'rotate(45deg)', border: `1px solid ${col}`, background: t >= c.t ? col : 'transparent'}} />
			))}
		</div>
	);
};

export const Phone: React.FC<{x: number; y: number; scale?: number; children?: React.ReactNode; light?: boolean; style?: React.CSSProperties}> = ({x, y, scale = 1, children, light, style}) => (
	<div
		style={{
			position: 'absolute',
			left: x - 210,
			top: y - 430,
			width: 420,
			height: 860,
			borderRadius: 64,
			background: light ? '#fafaf7' : '#0f1115',
			border: `10px solid ${light ? '#d9d8d2' : '#23262d'}`,
			boxShadow: '0 2px 4px rgba(0,0,0,.08), 0 20px 40px rgba(0,0,0,.18), 0 60px 120px rgba(0,0,0,.22)',
			overflow: 'hidden',
			transform: `scale(${scale})`,
			...style,
		}}
	>
		<div style={{position: 'absolute', left: 145, top: 14, width: 110, height: 32, borderRadius: 20, background: '#000', zIndex: 5}} />
		{children}
	</div>
);

/** A tool-call chip: spinner -> check */
export const Tool: React.FC<{t: number; at: number; done: number; label: string; detail: string; dark?: boolean}> = ({t, at, done, label, detail, dark = true}) => {
	const k = prog(t, at, 0.6, easeOut);
	const ok = t >= done;
	const spin = ((t - at) * 360 * 1.4) % 360;
	return (
		<div
			style={{
				display: 'flex',
				alignItems: 'center',
				gap: 18,
				padding: '18px 26px',
				borderRadius: 18,
				background: dark ? 'rgba(255,255,255,0.06)' : '#fff',
				border: `1px solid ${dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)'}`,
				opacity: k,
				transform: `translateY(${(1 - k) * 30}px)`,
				fontFamily: F.mono,
				fontSize: 22,
				color: dark ? '#e8e8e8' : C.ink,
				boxShadow: dark ? 'none' : '0 10px 30px rgba(0,0,0,.08)',
			}}
		>
			<div style={{width: 28, height: 28, position: 'relative'}}>
				{!ok && <div style={{position: 'absolute', inset: 2, borderRadius: '50%', border: '3px solid rgba(127,127,127,.3)', borderTopColor: C.water, transform: `rotate(${spin}deg)`}} />}
				{ok && (
					<svg width="28" height="28" viewBox="0 0 28 28">
						<circle cx="14" cy="14" r="13" fill={C.green} opacity={prog(t, done, 0.3)} />
						<path d="M8 14.5 L12.5 19 L20 9.5" fill="none" stroke="#06140c" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - prog(t, done, 0.35)} />
					</svg>
				)}
			</div>
			<span style={{color: C.waterSoft}}>{label}</span>
			<span style={{opacity: 0.7}}>{detail}</span>
		</div>
	);
};

export const Pill: React.FC<{children: React.ReactNode; bg: string; color?: string; size?: number; style?: React.CSSProperties}> = ({children, bg, color = '#fff', size = 24, style}) => (
	<div style={{display: 'inline-flex', alignItems: 'center', gap: 10, padding: `${size * 0.45}px ${size * 0.9}px`, borderRadius: 999, background: bg, color, fontFamily: F.sans, fontWeight: 600, fontSize: size, ...style}}>
		{children}
	</div>
);

/** soft layered shadow that grows with lift (0..1) */
export const lift = (k: number, dark = false) => {
	const a = dark ? 0.5 : 0.14;
	return `0 ${1 + k * 2}px ${2 + k * 4}px rgba(0,0,0,${a * 0.5}), 0 ${6 + k * 20}px ${16 + k * 40}px rgba(0,0,0,${a}), 0 ${20 + k * 60}px ${50 + k * 100}px rgba(0,0,0,${a * 0.8})`;
};

export const Center: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
	<div style={{position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', ...style}}>{children}</div>
);

export const SCREEN = {W, H};
