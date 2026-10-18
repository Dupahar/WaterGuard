import React from 'react';
import {Composition} from 'remotion';
import {Film} from './Film';
import {END, FPS, H, W} from './lib';
import {Product, PRODUCT_FRAMES} from './product/Product';

export const Root: React.FC = () => (
	<>
		<Composition id="Launch" component={Film} durationInFrames={Math.round(END * FPS)} fps={FPS} width={W} height={H} />
		<Composition id="Product" component={Product} durationInFrames={PRODUCT_FRAMES} fps={FPS} width={W} height={H} />
	</>
);
