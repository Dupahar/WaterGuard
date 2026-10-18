// Timing and data for the product film. Every cue is a word time from timeline.json (product_timeline.py).
import {continueRender, delayRender, staticFile} from 'remotion';
import timeline from './timeline.json';

export const PEND = timeline.end;
type Scene = {n: number; start: number; dur: number; words: [number, number, string][]};
const scenes = timeline.scenes as Scene[];
export const sStart = (n: number) => scenes[n - 1].start;
export const sEnd = (n: number) => scenes[n - 1].start + scenes[n - 1].dur;
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
/** time (s) when narration block n says `word` (nth occurrence) */
export const at = (n: number, word: string, nth = 0): number => {
	const hits = scenes[n - 1].words.filter((w) => norm(w[2]) === norm(word));
	const w = hits[nth] ?? hits[hits.length - 1];
	if (!w) throw new Error(`cue ${n} ${word}`);
	return w[0];
};
/** end time of that word */
export const atEnd = (n: number, word: string, nth = 0): number => {
	const hits = scenes[n - 1].words.filter((w) => norm(w[2]) === norm(word));
	return (hits[nth] ?? hits[hits.length - 1])[1];
};

export type Box = [number, number, number, number];
export type PData = {
	files: string[];
	report_root: string;
	claims_root: string;
	settlements: {name: string; status: number; people: number}[];
	facts: {impact_ha: number; cut: number; stranded: number; buildings: number; bridges: number};
	inspection: {confirmed: number; needs_review: number; pending_review: number; later_looks: number; cells: number; confirmed_ha: number};
	inspector_eval: any;
	validation: {aoi: number; name: string; split: string; f1: number}[];
	ledger: any;
	ui: {w: number; h: number; dpr: number; states: Record<string, {boxes: Record<string, Box | null>}>};
};
export type Cor = {ext: [number, number, number, number]; path: [number, number][]; places: {name: string; c: [number, number]}[]};

type D = {p: PData; cor: Cor};
let cache: D | null = null;
let pending: Promise<D> | null = null;
/** load once per bundle; delayRender keeps the frame from rendering before the data is there */
export const loadData = (): Promise<D> => {
	if (cache) return Promise.resolve(cache);
	if (!pending) {
		const h = delayRender('product data');
		pending = Promise.all([
			fetch(staticFile('data/product.json')).then((r) => r.json()),
			fetch(staticFile('data/corridor.json')).then((r) => r.json()),
		]).then(([p, cor]) => {
			cache = {p, cor};
			continueRender(h);
			return cache;
		});
	}
	return pending;
};
export const data = () => cache;
export const short = (h: string, a = 6, b = 4) => `${h.slice(0, 2 + a)}…${h.slice(-b)}`;
