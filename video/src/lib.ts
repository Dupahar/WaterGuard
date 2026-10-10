// Shared timing, easing, palette and data loading for the WaterGuard film.
import {continueRender, delayRender, Easing, staticFile} from 'remotion';
import {loadFont as geist} from '@remotion/google-fonts/Geist';
import {loadFont as geistMono} from '@remotion/google-fonts/GeistMono';
import {loadFont as serif} from '@remotion/google-fonts/InstrumentSerif';
import {loadFont as deva} from '@remotion/google-fonts/NotoSansDevanagari';
import timeline from './timeline.json';

export const FPS = 60;
export const W = 1920;
export const H = 1080;
export const END = timeline.end;

export const F = {
	sans: geist('normal', {weights: ['400', '500', '600', '700', '800', '900'], subsets: ['latin']}).fontFamily,
	mono: geistMono('normal', {weights: ['400', '500'], subsets: ['latin']}).fontFamily,
	serif: serif('italic', {subsets: ['latin']}).fontFamily,
	deva: deva('normal', {weights: ['500', '700'], subsets: ['devanagari']}).fontFamily,
};

export const C = {
	ink: '#0b0d11',
	ink2: '#14171d',
	paper: '#f2f1ec',
	paper2: '#e4e3dc',
	water: '#2f6bff',
	waterSoft: '#7aa2ff',
	red: '#ff3b2f',
	orange: '#ff6a2b',
	amber: '#ffbf2e',
	green: '#1fd17a',
	grey: '#3a3f4a',
	debris: '#c8461a',
};

export const ease = Easing.bezier(0.45, 0, 0.15, 1);
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
export const prog = (t: number, start: number, dur = 0.8, e = ease) => e(clamp((t - start) / dur));
export const win = (t: number, a: number, b: number, fi = 0.4, fo = 0.4) => Math.min(prog(t, a, fi), 1 - prog(t, b - fo, fo));

type Scene = {n: number; start: number; dur: number; words: [number, number, string][]};
const scenes = timeline.scenes as Scene[];
export const sceneStart = (n: number) => scenes[n - 1].start;
export const sceneEnd = (n: number) => scenes[n - 1].start + scenes[n - 1].dur;
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
/** global time (s) when narration scene `n` says `word` (nth occurrence) */
export const cue = (n: number, word: string | string[], nth = 0): number => {
	const opts = Array.isArray(word) ? word : [word];
	const key = opts.find((o) => scenes[n - 1].words.some((w) => norm(w[2]) === norm(o))) ?? opts[0];
	const hits = scenes[n - 1].words.filter((w) => norm(w[2]) === norm(key));
	const w = hits[nth] ?? hits[hits.length - 1];
	if (!w) throw new Error(`cue ${n} ${word}`);
	return w[0];
};

// ---------- data (real WaterGuard outputs, metres around each scene centre, y down) ----------
export type XY = [number, number];
export type Run = {
	ext: [number, number, number, number];
	facts: any;
	settlements: {name: string | null; b: number; s: string; sh?: number; c: XY}[];
	cut: string[];
	stranded?: {name: string; sh: number; p: number}[];
	buildings?: [number, number, number, number][]; // x, y, status 0/1/2, size m
	roads?: {h: string; l: XY[]}[];
	roads_cut?: XY[][];
	bridges?: {s: string; c: XY}[];
	path?: XY[][];
};
export type Corridor = {ext: [number, number, number, number]; path: XY[]; places: {name: string; c: XY}[]};
export type Data = {sya: Run; bid: Run; cor: Corridor; val: any[]};

let cache: Data | null = null;
let pending: Promise<Data> | null = null;
const j = (f: string) => fetch(staticFile(`data/${f}`)).then((r) => r.json());
export const useDataOnce = (): Promise<Data> => {
	if (cache) return Promise.resolve(cache);
	if (!pending) {
		const h = delayRender('data');
		pending = Promise.all([j('sya.json'), j('bid.json'), j('corridor.json'), j('validation.json')]).then(([sya, bid, cor, val]) => {
			cache = {sya, bid, cor, val};
			continueRender(h);
			return cache;
		});
	}
	return pending;
};
export const getData = () => cache;
