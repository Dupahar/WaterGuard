// Timing and data for the product film. Every cue is a word time from timeline.json (product_timeline.py).
import {continueRender, delayRender, staticFile} from 'remotion';
import timeline from './timeline.json';

export const PEND = timeline.end;
type Scene = {n: number; start: number; dur: number; words: [number, number, string][]};
const scenes = timeline.scenes as Scene[];
const sc = (n: number) => scenes.find((s) => s.n === n)!;   // blocks are not played in number order (13, 14 follow 8)
export const sStart = (n: number) => sc(n).start;
export const sEnd = (n: number) => sc(n).start + sc(n).dur;
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
/** time (s) when narration block n says `word` (nth occurrence) */
export const at = (n: number, word: string, nth = 0): number => {
	const hits = sc(n).words.filter((w) => norm(w[2]) === norm(word));
	const w = hits[nth] ?? hits[hits.length - 1];
	if (!w) throw new Error(`cue ${n} ${word}`);
	return w[0];
};
/** end time of that word */
export const atEnd = (n: number, word: string, nth = 0): number => {
	const hits = sc(n).words.filter((w) => norm(w[2]) === norm(word));
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
/** one real inspector cell under a 3 px misregistration (scripts/export_cv.py) */
export type Cv = {
	area: string; cell: string; window: [number, number]; cell_box: [number, number, number, number]; keypoints: [number, number];
	matches: [number, number, number, number, number][]; realign: {dx: number; dy: number; inliers: number; matches: number; residual_px: number};
	impact_ha: number; buildings_hit: number; verdict: string; ecc_only_verdict: string;
	zoom: {part: string; impact_ha: number; lines: Record<string, boolean>}[]; strong_parts: string[]; strong_share: number;
	trace: {step: string; tool?: string; lines?: Record<string, boolean>}[];
	robustness: {shift_px: number; variant: string; cells: number; confirmed_cells: number; false_confirmations: number; real_damage_ha_auto_confirmed_pct: number; realigned_cells: number}[];
};
/** real Nemotron outputs (scripts/export_nemotron.py) */
export type Nem = {
	planner: {model: string; cell: string; area: string; verdict: string; chip: string | null;
		trace: {step: string; tool?: string; action?: string; reason?: string; lines?: Record<string, boolean>; cause?: string; confidence?: number; explanation?: string}[]};
	copilot: {summary: {questions: number; answers_fully_verified: number; numbers_total: number; backend: string; median_seconds: number};
		web: {q: string; answer: string; web_numbers: string[]; sources: string[]; numbers: number}};
};
export type Cor = {ext: [number, number, number, number]; path: [number, number][]; places: {name: string; c: [number, number]}[]};

type D = {p: PData; cor: Cor; cv: Cv; nem: Nem};
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
			fetch(staticFile('data/cv/cell.json')).then((r) => r.json()),
			fetch(staticFile('data/nemotron/nemotron.json')).then((r) => r.json()),
		]).then(([p, cor, cv, nem]) => {
			cache = {p, cor, cv, nem};
			continueRender(h);
			return cache;
		});
	}
	return pending;
};
export const data = () => cache;
export const short = (h: string, a = 6, b = 4) => `${h.slice(0, 2 + a)}…${h.slice(-b)}`;
