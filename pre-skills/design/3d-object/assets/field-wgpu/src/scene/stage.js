/**
 * Renderer, camera rig, post chain and the frame loop.
 *
 * The stage takes exactly one instruction per frame — `phase` and `travel` —
 * and derives everything else: where the camera is, what colour the light is,
 * how much the image tears during a morph.
 */

import {
	NeutralToneMapping, PerspectiveCamera, RenderPipeline, Scene, Vector2, Vector3,
	WebGPURenderer
} from 'three';
import { clamp, dot, float, fract, pow, screenUV, sin, uniform, vec2, vec3, vec4, renderOutput, pass, Fn } from 'three/tsl';
import { bloom } from 'three/addons/tsl/display/BloomNode.js';

import { U, applyPalette } from './uniforms.js';
import { blendInto, createBlend, PHASE_MAX } from './palette.js';
import { createSky } from './sky.js';
import { createTerrain } from './terrain.js';
import { createField } from './field.js';

const TIERS = [
	{ count: 262144, dpr: 1.6, ground: true },
	{ count: 150000, dpr: 1.25, ground: true },
	{ count: 80000, dpr: 1.0, ground: true }
];

export async function createStage( canvas, { reducedMotion = false } = {} ) {

	const renderer = new WebGPURenderer( { canvas, antialias: false, alpha: false, powerPreference: 'high-performance' } );
	renderer.toneMapping = NeutralToneMapping;
	renderer.toneMappingExposure = 1.0;
	renderer.setClearColor( 0x000000, 1 );

	await renderer.init();

	const scene = new Scene();
	const camera = new PerspectiveCamera( 44, 1, 0.1, 2200 );

	const sky = createSky();
	const terrain = createTerrain();
	const field = createField( { count: TIERS[ 0 ].count } );

	scene.add( sky, terrain, field.mesh );

	/* ------------------------------------------------------------ post */

	const vignette = uniform( 0.45 );
	const grainAmount = uniform( 0.04 );

	const scenePass = pass( scene, camera );
	const sceneColor = scenePass.getTextureNode();
	const bloomPass = bloom( sceneColor, 0.65, 0.75, 0.7 );

	const postProcessing = new RenderPipeline( renderer );
	postProcessing.outputColorTransform = false;

	postProcessing.outputNode = Fn( () => {
		// lateral chromatic split, only really visible while the field morphs
		const offset = screenUV.sub( 0.5 );
		const k = U.warp.mul( 0.0055 ).add( 0.0009 );
		const lit = vec3(
			sceneColor.sample( screenUV.sub( offset.mul( k ) ) ).r,
			sceneColor.sample( screenUV ).g,
			sceneColor.sample( screenUV.add( offset.mul( k ) ) ).b
		).add( bloomPass.rgb );

		const falloff = clamp( float( 1 ).sub( dot( offset, offset ).mul( vignette.mul( 2.6 ) ) ), 0, 1 );
		const graded = lit.mul( pow( falloff, 1.35 ) );

		const seed = screenUV.mul( vec2( 1129.0, 977.0 ) ).add( U.time.mul( 101.0 ) );
		const grain = fract( sin( dot( seed, vec2( 12.9898, 78.233 ) ) ).mul( 43758.5453 ) ).sub( 0.5 );

		return renderOutput( vec4( graded, 1 ) ).add( vec4( vec3( grain.mul( grainAmount ) ), 0 ) );
	} )();

	/* ---------------------------------------------------------- state */

	const palette = createBlend();
	const camPos = new Vector3();
	const camTarget = new Vector3();
	const offset = new Vector3();
	const pointer = new Vector2();
	const pointerTarget = new Vector2();

	let elapsed = 0;
	let lastPhase = 0;
	let warp = 0;
	let fov = 44;
	let tier = 0;
	let slowFrames = 0;
	let fastFrames = 0;
	let frameMs = 16;

	function applyTier( i ) {
		tier = i;
		const t = TIERS[ i ];
		field.setVisibleCount( t.count );
		renderer.setPixelRatio( Math.min( window.devicePixelRatio || 1, t.dpr ) );
		renderer.setSize( window.innerWidth, window.innerHeight, false );
	}

	function resize() {
		camera.aspect = window.innerWidth / Math.max( 1, window.innerHeight );
		camera.updateProjectionMatrix();
		renderer.setPixelRatio( Math.min( window.devicePixelRatio || 1, TIERS[ tier ].dpr ) );
		renderer.setSize( window.innerWidth, window.innerHeight, false );
	}

	applyTier( 0 );
	resize();

	function setPointer( x, y ) {
		pointerTarget.set( x, y );
	}

	/**
	 * @param {number} dt seconds
	 * @param {{phase:number, travel:number}} drive
	 */
	function frame( dt, drive ) {
		const step = Math.min( dt, 0.05 );
		elapsed += step * ( reducedMotion ? 0.35 : 1 );

		const phase = Math.max( 0, Math.min( PHASE_MAX, drive.phase ) );
		const travel = drive.travel;

		// morph energy: how fast the field is currently changing shape
		const speed = Math.abs( phase - lastPhase ) / Math.max( step, 0.0001 );
		lastPhase = phase;
		warp += ( Math.min( speed * 0.85, 1 ) - warp ) * Math.min( 1, step * 7 );

		U.time.value = elapsed;
		U.phase.value = phase;
		U.warp.value = warp;

		blendInto( palette, phase );
		applyPalette( palette );

		renderer.toneMappingExposure = palette.exposure;
		bloomPass.strength.value = palette.bloom * ( 1 + warp * 0.55 );
		bloomPass.threshold.value = palette.bloomThreshold;
		vignette.value = palette.vignette;
		grainAmount.value = palette.grain;

		/* camera ------------------------------------------------------- */
		pointer.x += ( pointerTarget.x - pointer.x ) * Math.min( 1, step * 3.2 );
		pointer.y += ( pointerTarget.y - pointer.y ) * Math.min( 1, step * 3.2 );

		camPos.fromArray( palette.camPos );
		camTarget.fromArray( palette.camTarget );

		const orbit = travel * 0.62 + pointer.x * 0.11;
		offset.subVectors( camPos, camTarget );
		const cosA = Math.cos( orbit ), sinA = Math.sin( orbit );
		const ox = offset.x * cosA - offset.z * sinA;
		const oz = offset.x * sinA + offset.z * cosA;

		camera.position.set(
			camTarget.x + ox,
			camTarget.y + offset.y + Math.sin( elapsed * 0.23 ) * 0.11 - pointer.y * 0.55,
			camTarget.z + oz
		);
		// a tall viewport otherwise fills its top half with empty sky, so pitch
		// the camera down as the frame gets narrower
		const portrait = Math.max( 0, Math.min( 1, ( 1.15 - camera.aspect ) / 0.7 ) );

		camera.lookAt(
			camTarget.x + pointer.x * 2.4,
			camTarget.y - pointer.y * 1.5 + Math.sin( elapsed * 0.17 ) * 0.08 - portrait * 3.6,
			camTarget.z
		);

		if ( Math.abs( palette.fov - fov ) > 0.01 ) {
			fov = palette.fov;
			camera.fov = fov;
			camera.updateProjectionMatrix();
		}

		sky.position.copy( camera.position );
		U.camPos.value.copy( camera.position );

		/* draw --------------------------------------------------------- */
		const t0 = performance.now();
		renderer.compute( field.computeNode );
		postProcessing.render();
		frameMs += ( ( performance.now() - t0 ) - frameMs ) * 0.05;

		/* adapt -------------------------------------------------------- */
		const budget = step * 1000;
		if ( budget > 21 ) { slowFrames ++; fastFrames = 0; } else if ( budget < 13 ) { fastFrames ++; slowFrames = 0; }
		if ( slowFrames > 90 && tier < TIERS.length - 1 ) { applyTier( tier + 1 ); slowFrames = 0; }
		else if ( fastFrames > 400 && tier > 0 ) { applyTier( tier - 1 ); fastFrames = 0; }
	}

	return {
		renderer, scene, camera, palette, frame, resize, setPointer,
		get instanceCount() { return TIERS[ tier ].count; },
		get frameMs() { return frameMs; },
		dispose() { renderer.dispose(); }
	};
}
