import React from 'react';
import {Composition} from 'remotion';
import {MarketingVideo} from './MarketingVideo';
import {FPS, TOTAL_DURATION_IN_FRAMES} from './video-config';

export const RemotionRoot = () => {
	// Duration, fps, and all scene/overlay/transition data come from the
	// AGENT_MANAGED video-config.ts, which the Python agent regenerates before
	// every render. There is no regex patching of this file anymore.
	return (
		<Composition
			id="MarketingVideo"
			component={MarketingVideo}
			durationInFrames={TOTAL_DURATION_IN_FRAMES}
			fps={FPS}
			width={1080}
			height={1920}
		/>
	);
};
