// A shorter cut of the product film: replays the film's own frames for the blocks in short.json
// (scripts/short_timeline.py) on a new clock, cross-fading between segments, with one HUD that counts
// the cut's time and renumbers its chapters. Audio: product_mix.py on short_timeline.json (see short_timeline.py).
import React from 'react';
import {AbsoluteFill, Audio, staticFile, useCurrentFrame} from 'remotion';
import {C, clamp, FPS} from '../lib';
import {ChapterLabels, Hud, Stage} from './Product';
import short from './short.json';

export const SHORT_FRAMES = Math.round(short.end * FPS);
const labels = Object.fromEntries(Object.entries(short.labels).map(([k, v]) => [Number(k), v]));

export const Short: React.FC = () => {
	const T = useCurrentFrame() / FPS;
	const live = short.segments.map((s, i) => ({...s, i})).filter((s) => T >= s.out && T < s.out + (s.to - s.from));
	const top = live[live.length - 1] ?? short.segments[short.segments.length - 1];
	return (
		<ChapterLabels.Provider value={labels}>
			<AbsoluteFill style={{background: C.ink}}>
				{live.map((s) => (
					<AbsoluteFill key={s.i} style={{opacity: s.i === 0 ? 1 : clamp((T - s.out) / short.xfade)}}>
						<Stage t={s.from + T - s.out} hud={false} />
					</AbsoluteFill>
				))}
				<Hud t={top.from + T - top.out} clock={{t: T, end: short.end, marks: short.marks}} />
				<Audio src={staticFile('audio/short_mix.wav')} />
			</AbsoluteFill>
		</ChapterLabels.Provider>
	);
};
