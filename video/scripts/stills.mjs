// Render stills at given seconds (fast review). Usage: node scripts/stills.mjs out/dir 1.5 3 10 ...
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition, openBrowser} from '@remotion/renderer';
import path from 'node:path';
import fs from 'node:fs';

const [dir, ...secs] = process.argv.slice(2);
fs.mkdirSync(dir, {recursive: true});
const serveUrl = await bundle({entryPoint: path.resolve('src/index.ts')});
const browser = await openBrowser('chrome', {chromiumOptions: {gl: 'angle'}});
const composition = await selectComposition({serveUrl, id: 'Launch', puppeteerInstance: browser});
for (const s of secs) {
	const frame = Math.min(composition.durationInFrames - 1, Math.round(Number(s) * composition.fps));
	const out = path.join(dir, `t${String(Number(s).toFixed(2)).padStart(7, '0')}.jpg`);
	await renderStill({composition, serveUrl, output: out, frame, scale: 0.5, imageFormat: 'jpeg', jpegQuality: 80, puppeteerInstance: browser});
	console.log('ok', s);
}
await browser.close({silent: true});
