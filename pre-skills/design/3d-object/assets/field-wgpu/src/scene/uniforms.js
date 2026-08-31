/**
 * The whole scene is driven by this handful of uniforms.
 *
 * `phase` (0..3) is the only thing the page really controls: it selects the
 * state of the field. Everything else is either derived from it on the CPU
 * (see palette.js) or is plain time.
 */

import { Color, Vector3 } from 'three';
import { uniform } from 'three/tsl';

export const U = {
	phase: uniform( 0 ),
	time: uniform( 0 ),
	// spikes to 1 while the field is morphing — drives gusts, aberration, extra bloom
	warp: uniform( 0 ),
	// the compute pass has no camera bindings of its own
	camPos: uniform( new Vector3( 0, 0, 0 ) ),

	sunDir: uniform( new Vector3( 0.1, 0.06, - 1 ).normalize() ),
	sunColor: uniform( new Color( 1, 1, 1 ) ),
	sunIntensity: uniform( 2.6 ),

	skyZenith: uniform( new Color( 0, 0, 0 ) ),
	skyHorizon: uniform( new Color( 0, 0, 0 ) ),
	skyLow: uniform( new Color( 0, 0, 0 ) ),
	cloud: uniform( 1 ),
	star: uniform( 0 ),

	fogColor: uniform( new Color( 0, 0, 0 ) ),
	fogDensity: uniform( 0.01 ),
	fogHeight: uniform( 0.05 ),

	groundColor: uniform( new Color( 0, 0, 0 ) ),
	groundTint: uniform( new Color( 0, 0, 0 ) ),
	ambient: uniform( new Color( 0, 0, 0 ) ),
	ambientAmount: uniform( 0.4 ),
	translucency: uniform( 1.4 )
};

const setColor = ( u, rgb ) => u.value.setRGB( rgb[ 0 ], rgb[ 1 ], rgb[ 2 ] );

/** Push a blended palette (from palette.blendInto) into the GPU uniforms. */
export function applyPalette( p ) {
	U.sunDir.value.set( p.sunDir[ 0 ], p.sunDir[ 1 ], p.sunDir[ 2 ] ).normalize();
	setColor( U.sunColor, p.sunColor );
	U.sunIntensity.value = p.sunIntensity;

	setColor( U.skyZenith, p.skyZenith );
	setColor( U.skyHorizon, p.skyHorizon );
	setColor( U.skyLow, p.skyLow );
	U.cloud.value = p.cloud;
	U.star.value = p.star;

	setColor( U.fogColor, p.fogColor );
	U.fogDensity.value = p.fogDensity;
	U.fogHeight.value = p.fogHeight;

	setColor( U.groundColor, p.groundColor );
	setColor( U.groundTint, p.groundTint );
	setColor( U.ambient, p.ambient );
	U.ambientAmount.value = p.ambientAmount;
	U.translucency.value = p.translucency;
}
