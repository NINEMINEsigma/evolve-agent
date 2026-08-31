/**
 * Procedural sky dome. No cubemap, no HDRI — a gradient, a sun, a cloud deck
 * projected onto a plane, and a star field, all keyed off the blended palette.
 */

import { BackSide, Mesh, MeshBasicNodeMaterial, SphereGeometry } from 'three';
import {
	Fn, vec2, vec3, float, abs, clamp, dot, pow, mix, smoothstep, step, sin, floor, fract,
	length, normalize, max, positionWorld, cameraPosition, screenCoordinate,
	mx_noise_float, mx_fractal_noise_float, mx_cell_noise_float, interleavedGradientNoise
} from 'three/tsl';

import { U } from './uniforms.js';

export function createSky() {
	const material = new MeshBasicNodeMaterial( {
		side: BackSide,
		depthWrite: false,
		depthTest: false,
		fog: false
	} );

	material.colorNode = Fn( () => {
		const dir = normalize( positionWorld.sub( cameraPosition ) );
		const h = dir.y;
		const t = U.time;

		/* gradient ------------------------------------------------------- */
		const upper = mix( U.skyHorizon, U.skyZenith.mul( 1.25 ), pow( clamp( h, 0, 1 ), 0.75 ) );
		const lower = mix( U.skyLow, U.skyHorizon, clamp( h.mul( 11 ).add( 1 ), 0, 1 ) );
		const col = mix( lower, upper, smoothstep( - 0.02, 0.03, h ) ).toVar();

		/* warm band hugging the horizon in the sun's direction ------------ */
		const sd = clamp( dot( dir, U.sunDir ), 0, 1 );
		const band = pow( sd, 3.2 ).mul( float( 1 ).sub( smoothstep( 0.0, 0.46, abs( h ) ) ) );
		col.addAssign( U.sunColor.mul( U.sunIntensity.mul( 0.34 ) ).mul( band ) );

		/* cloud deck ------------------------------------------------------ */
		const cd = max( h, 0.035 );
		const flat = dir.xz.div( cd );
		const cuv = flat.mul( 0.5 ).add( vec2( t.mul( 0.035 ), t.mul( 0.021 ) ) );
		const n = mx_fractal_noise_float( vec3( cuv, t.mul( 0.02 ) ), 4, 2.2, 0.48 );
		const wisp = mx_noise_float( vec3( cuv.mul( 3.4 ), t.mul( 0.03 ) ) ).mul( 0.28 );

		const cover = smoothstep( 0.12, 0.62, n.add( wisp ) )
			.mul( float( 1 ).sub( smoothstep( 8.0, 22.0, length( flat ) ) ) )
			.mul( smoothstep( 0.0, 0.05, h ) )
			.mul( U.cloud )
			.mul( 0.5 );

		const shade = U.fogColor.mul( 0.36 );
		const lit = U.sunColor.mul( U.sunIntensity.mul( 0.26 ) );
		const cloudCol = mix( shade, lit, clamp( pow( sd, 2.5 ).mul( 0.9 ).add( 0.1 ), 0, 1 ) );
		col.assign( mix( col, cloudCol, cover ) );

		/* sun — dimmed by whatever cloud sits in front of it --------------- */
		const above = smoothstep( - 0.03, 0.04, U.sunDir.y );
		const disc = smoothstep( 0.99958, 0.99978, sd ).mul( above );
		const glow = pow( sd, 4000.0 ).mul( 1.4 )
			.add( pow( sd, 1400.0 ).mul( 0.32 ) )
			.add( pow( sd, 28.0 ).mul( 0.09 ) );
		col.addAssign(
			U.sunColor.mul( U.sunIntensity )
				.mul( disc.mul( 7.0 ).add( glow ) )
				.mul( float( 1 ).sub( cover.mul( 0.82 ) ) )
		);

		/* stars ------------------------------------------------------------ */
		const q = dir.mul( 130.0 );
		const seed = mx_cell_noise_float( floor( q ) );
		const bright = smoothstep( 0.985, 0.9995, seed );
		const dotMask = smoothstep( 0.36, 0.03, length( fract( q ).sub( 0.5 ) ) );
		const twinkle = sin( t.mul( 2.1 ).add( seed.mul( 240.0 ) ) ).mul( 0.35 ).add( 0.65 );
		const starVis = U.star.mul( smoothstep( - 0.01, 0.18, h ) ).mul( step( 0.0, h ) );
		col.addAssign( vec3( 0.72, 0.84, 1.0 ).mul( bright.mul( dotMask ).mul( twinkle ).mul( starVis ).mul( 1.8 ) ) );

		/* dither out the banding in the gradient --------------------------- */
		col.addAssign( interleavedGradientNoise( screenCoordinate.xy ).sub( 0.5 ).mul( 0.0045 ) );

		return max( col, vec3( 0 ) );
	} )();

	const mesh = new Mesh( new SphereGeometry( 900, 48, 32 ), material );
	mesh.frustumCulled = false;
	mesh.renderOrder = - 1000;
	mesh.name = 'sky';
	return mesh;
}
