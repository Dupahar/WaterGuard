import React from 'react';
import {Composition} from 'remotion';
import {Film} from './Film';
import {END, FPS, H, W} from './lib';

export const Root: React.FC = () => (
	<Composition id="Launch" component={Film} durationInFrames={Math.round(END * FPS)} fps={FPS} width={W} height={H} />
);
