/**
 * Shared TSL building blocks: state blending, cheap per-instance randomness,
 * the morphing height field, and atmosphere.
 *
 * The height field is the spine of the scene — the ground mesh displaces with
 * it and the compute pass plants every strand on it, so the two can never
 * disagree.
 */

import {
	Fn, If, float, vec2, vec3, hash, uint, sin, cos, max, min, clamp, exp, pow, round,
	smoothstep, mix, mx_noise_float, mx_fractal_noise_float, normalize, dot, length,
	cameraPosition, positionWorld
} from 'three/tsl';

import { U } from './uniforms.js';
import { STATE_COUNT } from './palette.js';

export const FIELD_RADIUS = 130;
export const GROUND_SIZE = 460;

/**
 * The camera walks a small area around the origin, so the solid terrain is
 * flattened there into a clearing and the relief ramps in further out. It also
 * means the camera can never end up inside a hill.
 */
const clearing = ( p ) => smoothstep( 14, 62, length( p ) );

/* --------------------------------------------------------- state blending */

/** Smoothstepped tent weights; adjacent pairs sum to exactly 1. */
export function stateWeights( phase = U.phase ) {
	const w = [];
	for ( let k = 0; k < STATE_COUNT; k ++ ) {
		w.push( smoothstep( 0, 1, float( 1 ).sub( phase.sub( float( k ) ).abs() ) ) );
	}
	return w;
}

/**
 * Blend four per-state expressions. `make[k]()` is only evaluated when its
 * state carries weight, so at most two states are ever computed per frame.
 * Must be called from inside an Fn (it opens conditional blocks).
 */
export function blendStates( make, type = 'float' ) {
	const w = stateWeights();
	const zero = type === 'float' ? float( 0 ) : type === 'vec2' ? vec2( 0 ) : vec3( 0 );
	const acc = zero.toVar();
	for ( let k = 0; k < STATE_COUNT; k ++ ) {
		If( w[ k ].greaterThan( 0.0005 ), () => {
			acc.addAssign( make[ k ]().mul( w[ k ] ) );
		} );
	}
	return acc;
}

/* ------------------------------------------------------------ randomness */

/** Eight independent uniform randoms per instance id. */
export const rnd = ( id, slot ) => hash( id.mul( uint( 8 ) ).add( uint( slot ) ) );

/* ---------------------------------------------------------- height field */

const hMeadow = ( p ) => {
	const big = mx_fractal_noise_float( vec3( p.mul( 0.0085 ), 0.0 ), 4, 2.05, 0.5 ).mul( 9.5 );
	const mid = mx_noise_float( vec3( p.mul( 0.042 ), 3.7 ) ).mul( 0.95 );
	const fine = mx_noise_float( vec3( p.mul( 0.19 ), 11.3 ) ).mul( 0.14 );
	return big.add( mid ).mul( clearing( p ) ).add( fine ).sub( 0.35 );
};

const hTide = ( p ) => {
	const t = U.time;
	const w1 = sin( p.x.mul( 0.062 ).add( p.y.mul( 0.037 ) ).add( t.mul( 0.52 ) ) ).mul( 1.35 );
	const w2 = sin( p.x.mul( - 0.058 ).add( p.y.mul( 0.124 ) ).add( t.mul( 0.79 ) ) ).mul( 0.68 );
	const w3 = sin( p.x.mul( 0.271 ).add( p.y.mul( - 0.038 ) ).add( t.mul( 1.31 ) ) ).mul( 0.2 );
	const chop = mx_fractal_noise_float( vec3( p.mul( 0.085 ), t.mul( 0.12 ) ), 3, 2.1, 0.55 ).mul( 0.42 );
	return w1.add( w2 ).add( w3 ).add( chop ).sub( 0.2 );
};

const hEmber = ( p ) => {
	const n = mx_fractal_noise_float( vec3( p.mul( 0.0075 ), 21.0 ), 4, 2.15, 0.55 );
	const ridge = n.abs().oneMinus();
	const dune = pow( ridge, 2.4 ).mul( 15.0 ).sub( 2.4 );
	const grit = mx_noise_float( vec3( p.mul( 0.11 ), 5.0 ) ).mul( 0.3 );
	return dune.mul( clearing( p ) ).add( grit ).sub( 0.4 );
};

const hLattice = ( p ) => {
	const n = mx_fractal_noise_float( vec3( p.mul( 0.011 ), 41.0 ), 3, 2.0, 0.5 );
	// terraced — the ground itself quantises
	return round( n.mul( 16.0 ) ).div( 2.0 ).mul( clearing( p ) ).sub( 0.3 );
};

const HEIGHT_FNS = [ hMeadow, hTide, hEmber, hLattice ];

/** World-space ground height at xz, blended across the active states. */
export const surfaceHeight = /*#__PURE__*/ Fn( ( [ p ] ) => {
	return blendStates( HEIGHT_FNS.map( ( f ) => () => f( p ) ) );
} );

/** Ground normal by central differences of the blended height field. */
export const surfaceNormal = /*#__PURE__*/ Fn( ( [ p, e ] ) => {
	const hx = surfaceHeight( p.add( vec2( e, 0 ) ) ).sub( surfaceHeight( p.sub( vec2( e, 0 ) ) ) );
	const hz = surfaceHeight( p.add( vec2( 0, e ) ) ).sub( surfaceHeight( p.sub( vec2( 0, e ) ) ) );
	return normalize( vec3( hx.negate(), e.mul( 4 ), hz.negate() ) );
} );

/* ------------------------------------------------------------------- wind */

/**
 * One wind field sampled in world space: slow travelling gusts plus a faster
 * swirl. Returns (direction.xy, strength).
 */
export const windAt = /*#__PURE__*/ Fn( ( [ p ] ) => {
	const t = U.time;
	const drift = vec2( t.mul( - 1.9 ), t.mul( - 1.15 ) );
	const gust = mx_fractal_noise_float( vec3( p.add( drift ).mul( 0.017 ), t.mul( 0.06 ) ), 3, 2.0, 0.5 );
	const swirl = mx_noise_float( vec3( p.add( drift ).mul( 0.06 ), t.mul( 0.35 ) ) );
	const angle = float( 0.62 ).add( swirl.mul( 0.55 ) ).add( gust.mul( 0.3 ) );
	const strength = gust.mul( 0.5 ).add( 0.5 ).mul( swirl.mul( 0.28 ).add( 0.82 ) );
	return vec3( cos( angle ), sin( angle ), strength );
} );

/* -------------------------------------------------------------- atmosphere */

/**
 * Height-attenuated exponential-squared fog, tinted toward the sun so looking
 * into the light produces real haze instead of a flat wash.
 */
export const applyFog = /*#__PURE__*/ Fn( ( [ color ] ) => {
	const toCam = positionWorld.sub( cameraPosition );
	const dist = length( toCam );
	const viewDir = toCam.div( max( dist, 0.0001 ) );

	const heightFall = exp( max( positionWorld.y, - 6 ).mul( U.fogHeight.negate() ) );
	const d = dist.mul( U.fogDensity ).mul( heightFall );
	const amount = float( 1 ).sub( exp( d.mul( d ).negate() ) );

	const towardSun = clamp( dot( viewDir, U.sunDir ), 0, 1 );
	const hazeSun = pow( towardSun, 3.5 ).mul( 0.6 ).add( pow( towardSun, 22.0 ).mul( 1.1 ) );
	const haze = mix( U.fogColor, U.sunColor.mul( U.sunIntensity.mul( 0.3 ) ), min( hazeSun, 0.82 ) );

	return mix( color, haze, clamp( amount, 0, 1 ) );
} );
