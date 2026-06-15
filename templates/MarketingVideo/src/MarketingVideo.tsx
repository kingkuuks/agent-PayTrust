import React from 'react';
import {
	AbsoluteFill,
	Img,
	useCurrentFrame,
	useVideoConfig,
	interpolate,
	spring,
	Easing,
	staticFile,
} from 'remotion';
import {Audio} from '@remotion/media';
import {
	TransitionSeries,
	linearTiming,
	type TransitionPresentation,
} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {slide} from '@remotion/transitions/slide';
import {wipe} from '@remotion/transitions/wipe';
import {flip} from '@remotion/transitions/flip';
import {clockWipe} from '@remotion/transitions/clock-wipe';

import {
	SCENES,
	HAS_BGM,
	TRANSITIONS,
	TRANSITION_FRAMES,
	type SceneRenderConfig,
} from './video-config';

// Brand palette (mirrors config/brand.json). Text is rendered live here in
// Remotion; photo PNGs no longer have baked-in overlay text.
const BRAND = {
	primary: '#1F6FEB',
	secondary: '#0D1117',
	accent: '#FFD700',
	text: '#FFFFFF',
};

const SCENE_COUNT = SCENES.length;
const FLASH_FRAMES = 4;

type Motion = {zoomStart: number; zoomEnd: number; panX: number; panY: number};

// Subtle Ken Burns motion; varies by scene so the slideshow feel is reduced.
const MOTIONS: Motion[] = [
	{zoomStart: 1.04, zoomEnd: 1.1, panX: 0, panY: -20},
	{zoomStart: 1.0, zoomEnd: 1.09, panX: 24, panY: 0},
	{zoomStart: 1.09, zoomEnd: 1.0, panX: -24, panY: 0},
	{zoomStart: 1.0, zoomEnd: 1.07, panX: 0, panY: 24},
	{zoomStart: 1.05, zoomEnd: 1.0, panX: 0, panY: 0},
];

const presentationFor = (
	name: string,
	width: number,
	height: number,
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
): TransitionPresentation<any> => {
	switch (name) {
		case 'slide':
			return slide();
		case 'wipe':
			return wipe();
		case 'flip':
			return flip();
		case 'clockWipe':
			return clockWipe({width, height});
		case 'fade':
		default:
			return fade();
	}
};

const CutFlash: React.FC = () => {
	const frame = useCurrentFrame();
	if (frame >= FLASH_FRAMES) {
		return null;
	}
	const opacity = interpolate(frame, [0, FLASH_FRAMES], [0.85, 0], {
		extrapolateRight: 'clamp',
	});
	return (
		<AbsoluteFill style={{backgroundColor: '#FFFFFF', opacity}} />
	);
};

const SceneTextOverlay: React.FC<{text: string; isHero: boolean}> = ({
	text,
	isHero,
}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const entrance = spring({frame, fps, config: {damping: 200}, durationInFrames: 18});
	const opacity = interpolate(entrance, [0, 1], [0, 1]);
	const translateY = interpolate(entrance, [0, 1], [48, 0]);

	if (!text) {
		return null;
	}

	if (isHero) {
		const scale = interpolate(entrance, [0, 1], [0.86, 1]);
		return (
			<AbsoluteFill
				style={{
					justifyContent: 'center',
					alignItems: 'center',
					padding: '0 80px',
				}}
			>
				<div
					style={{
						opacity,
						transform: `translateY(${translateY}px) scale(${scale})`,
						textAlign: 'center',
					}}
				>
					<div
						style={{
							fontFamily: 'Arial, Helvetica, sans-serif',
							fontWeight: 800,
							fontSize: 96,
							lineHeight: 1.05,
							color: BRAND.text,
							textShadow: '0 4px 24px rgba(0,0,0,0.85)',
						}}
					>
						{text}
					</div>
					<div
						style={{
							marginTop: 28,
							marginLeft: 'auto',
							marginRight: 'auto',
							width: 220,
							height: 6,
							borderRadius: 3,
							backgroundColor: BRAND.primary,
						}}
					/>
				</div>
			</AbsoluteFill>
		);
	}

	return (
		<AbsoluteFill
			style={{
				justifyContent: 'flex-end',
				alignItems: 'center',
				padding: '0 50px 170px',
			}}
		>
			<div
				style={{
					opacity,
					transform: `translateY(${translateY}px)`,
					width: '100%',
					maxWidth: 980,
					backgroundColor: 'rgba(13,17,23,0.62)',
					borderRadius: 24,
					borderTop: `4px solid ${BRAND.primary}`,
					padding: '34px 40px',
				}}
			>
				<div
					style={{
						fontFamily: 'Arial, Helvetica, sans-serif',
						fontWeight: 700,
						fontSize: 70,
						lineHeight: 1.1,
						color: BRAND.text,
						textAlign: 'center',
						textShadow: '0 2px 12px rgba(0,0,0,0.7)',
					}}
				>
					{text}
				</div>
			</div>
		</AbsoluteFill>
	);
};

const SceneComponent: React.FC<{
	scene: SceneRenderConfig;
	sceneDurationInFrames: number;
	isLast: boolean;
}> = ({scene, sceneDurationInFrames, isLast}) => {
	const frame = useCurrentFrame();
	const idx = String(scene.index).padStart(2, '0');
	const imagePath = staticFile(`scenes/scene_${idx}.png`);
	const audioPath = staticFile(`audio/audio_${idx}.mp3`);

	const motion = MOTIONS[scene.index] || MOTIONS[1];
	const scale = interpolate(
		frame,
		[0, sceneDurationInFrames],
		[motion.zoomStart, motion.zoomEnd],
		{extrapolateRight: 'clamp', easing: Easing.inOut(Easing.quad)},
	);
	const translateX = interpolate(
		frame,
		[0, sceneDurationInFrames],
		[0, motion.panX],
		{extrapolateRight: 'clamp'},
	);
	const translateY = interpolate(
		frame,
		[0, sceneDurationInFrames],
		[0, motion.panY],
		{extrapolateRight: 'clamp'},
	);

	const isPhoto = scene.visualType === 'photo';
	const isHero = scene.index === 0 || isLast;
	const showFlash = scene.index === 1 || isLast;

	return (
		<AbsoluteFill style={{backgroundColor: '#000000'}}>
			<div
				style={{
					width: '100%',
					height: '100%',
					transform: `scale(${scale}) translate(${translateX}px, ${translateY}px)`,
					overflow: 'hidden',
				}}
			>
				<Img
					src={imagePath}
					style={{width: '100%', height: '100%', objectFit: 'cover'}}
				/>
			</div>
			{/* text_card PNGs already contain their own typography; only photo
			    scenes get the live Remotion overlay to avoid duplicate text. */}
			{isPhoto && <SceneTextOverlay text={scene.textOverlay} isHero={isHero} />}
			{showFlash && <CutFlash />}
			<Audio src={audioPath} />
		</AbsoluteFill>
	);
};

export const MarketingVideo: React.FC = () => {
	const {width, height} = useVideoConfig();

	const sequenceDurations = SCENES.map((scene, i) =>
		i < SCENE_COUNT - 1
			? scene.baseDurationInFrames + TRANSITION_FRAMES
			: scene.baseDurationInFrames,
	);

	const children: React.ReactNode[] = [];
	SCENES.forEach((scene, i) => {
		children.push(
			<TransitionSeries.Sequence
				key={`scene-${i}`}
				durationInFrames={sequenceDurations[i]}
			>
				<SceneComponent
					scene={scene}
					sceneDurationInFrames={sequenceDurations[i]}
					isLast={i === SCENE_COUNT - 1}
				/>
			</TransitionSeries.Sequence>,
		);
		if (i < SCENE_COUNT - 1) {
			children.push(
				<TransitionSeries.Transition
					key={`transition-${i}`}
					presentation={presentationFor(
						TRANSITIONS[i] || 'fade',
						width,
						height,
					)}
					timing={linearTiming({durationInFrames: TRANSITION_FRAMES})}
				/>,
			);
		}
	});

	return (
		<AbsoluteFill style={{backgroundColor: '#000000'}}>
			{HAS_BGM && <Audio src={staticFile('audio/bgm.mp3')} volume={0.15} />}
			<TransitionSeries>{children}</TransitionSeries>
		</AbsoluteFill>
	);
};
