/**
 * Art direction for the four states of the field.
 *
 * Everything that varies smoothly over the whole frame (sky colours, sun, fog,
 * camera, bloom) is blended here on the CPU and pushed into single uniforms.
 * Only things that vary per-position or per-strand are blended inside shaders.
 */

export const STATES = [
	{
		id: 'meadow',
		numeral: 'I',
		name: '草场',
		accent: '#e8c37a',

		skyZenith: '#356fb4',
		skyHorizon: '#f2b878',
		skyLow: '#c98a52',
		sunColor: '#fff1cf',
		sunIntensity: 2.4,
		sunDir: [0.10, 0.055, -1],
		cloud: 1.0,
		star: 0.0,

		fogColor: '#c98a52',
		fogDensity: 0.0080,
		fogHeight: 0.055,

		groundColor: '#2a3a1c',
		groundTint: '#7d8a3a',
		ambient: '#5f7fa8',
		ambientAmount: 0.42,
		translucency: 1.55,

		camPos: [0.6, 1.3, 13.0],
		camTarget: [0.0, 2.0, -9.0],
		fov: 44,

		bloom: 0.5,
		bloomThreshold: 0.86,
		exposure: 0.98,
		grain: 0.035,
		vignette: 0.42
	},
	{
		id: 'tide',
		numeral: 'II',
		name: '潮汐',
		accent: '#7fd7d2',

		skyZenith: '#112a4a',
		skyHorizon: '#e0714b',
		skyLow: '#243550',
		sunColor: '#ffb682',
		sunIntensity: 3.1,
		sunDir: [-0.34, 0.028, -1],
		cloud: 0.75,
		star: 0.25,

		fogColor: '#20344f',
		fogDensity: 0.0128,
		fogHeight: 0.07,

		groundColor: '#05192c',
		groundTint: '#12707d',
		ambient: '#2b4a72',
		ambientAmount: 0.5,
		translucency: 1.15,

		camPos: [0.0, 6.6, 19.0],
		camTarget: [0.0, 2.4, -16.0],
		fov: 46,

		bloom: 0.58,
		bloomThreshold: 0.8,
		exposure: 1.0,
		grain: 0.045,
		vignette: 0.5
	},
	{
		id: 'ember',
		numeral: 'III',
		name: '余烬',
		accent: '#ff7a3c',

		skyZenith: '#04060c',
		skyHorizon: '#411208',
		skyLow: '#150705',
		sunColor: '#ff5a1e',
		sunIntensity: 1.5,
		sunDir: [0.22, -0.10, -1],
		cloud: 0.35,
		star: 0.85,

		fogColor: '#1b0a07',
		fogDensity: 0.0155,
		fogHeight: 0.05,

		groundColor: '#0b0707',
		groundTint: '#59180a',
		ambient: '#3a1408',
		ambientAmount: 0.34,
		translucency: 0.55,

		camPos: [0.0, 8.2, 24.0],
		camTarget: [0.0, 6.4, -18.0],
		fov: 48,

		bloom: 0.62,
		bloomThreshold: 0.68,
		exposure: 1.0,
		grain: 0.055,
		vignette: 0.58
	},
	{
		id: 'lattice',
		numeral: 'IV',
		name: '晶格',
		accent: '#63e8ff',

		skyZenith: '#01030a',
		skyHorizon: '#052430',
		skyLow: '#020609',
		sunColor: '#9fe9ff',
		sunIntensity: 0.55,
		sunDir: [0.0, 0.30, -1],
		cloud: 0.0,
		star: 1.0,

		fogColor: '#04121a',
		fogDensity: 0.0135,
		fogHeight: 0.045,

		groundColor: '#02070c',
		groundTint: '#0a4d63',
		ambient: '#0b2f47',
		ambientAmount: 0.3,
		translucency: 0.2,

		camPos: [0.0, 13.5, 28.0],
		camTarget: [0.0, 2.4, -14.0],
		fov: 46,

		bloom: 0.55,
		bloomThreshold: 0.62,
		exposure: 1.02,
		grain: 0.03,
		vignette: 0.52
	}
];

export const STATE_COUNT = STATES.length;
export const PHASE_MAX = STATE_COUNT - 1;

/* ---------------------------------------------------------------- helpers */

const smooth = ( t ) => ( t <= 0 ? 0 : t >= 1 ? 1 : t * t * ( 3 - 2 * t ) );

/** Tent weights, smoothstepped. Adjacent pairs always sum to exactly 1. */
export function weights( phase ) {
	const w = new Array( STATE_COUNT );
	for ( let k = 0; k < STATE_COUNT; k ++ ) w[ k ] = smooth( 1 - Math.abs( phase - k ) );
	return w;
}

const SRGB_CACHE = new Map();

/** '#rrggbb' -> linear-sRGB triplet, memoised. */
export function linear( hex ) {
	let c = SRGB_CACHE.get( hex );
	if ( c ) return c;
	const n = parseInt( hex.slice( 1 ), 16 );
	const to = ( v ) => ( v <= 0.04045 ? v / 12.92 : Math.pow( ( v + 0.055 ) / 1.055, 2.4 ) );
	c = [ to( ( n >> 16 & 255 ) / 255 ), to( ( n >> 8 & 255 ) / 255 ), to( ( n & 255 ) / 255 ) ];
	SRGB_CACHE.set( hex, c );
	return c;
}

const COLOR_KEYS = [ 'skyZenith', 'skyHorizon', 'skyLow', 'sunColor', 'fogColor', 'groundColor', 'groundTint', 'ambient' ];
const VEC_KEYS = [ 'sunDir', 'camPos', 'camTarget' ];
const NUM_KEYS = [ 'sunIntensity', 'cloud', 'star', 'fogDensity', 'fogHeight', 'ambientAmount',
	'translucency', 'fov', 'bloom', 'bloomThreshold', 'exposure', 'grain', 'vignette' ];

/** Reusable blend target so the render loop allocates nothing. */
export function createBlend() {
	const out = {};
	for ( const k of COLOR_KEYS ) out[ k ] = [ 0, 0, 0 ];
	for ( const k of VEC_KEYS ) out[ k ] = [ 0, 0, 0 ];
	for ( const k of NUM_KEYS ) out[ k ] = 0;
	out.accent = STATES[ 0 ].accent;
	out.name = STATES[ 0 ].name;
	return out;
}

export function blendInto( out, phase ) {
	const w = weights( phase );

	for ( const k of COLOR_KEYS ) {
		const t = out[ k ];
		t[ 0 ] = t[ 1 ] = t[ 2 ] = 0;
		for ( let i = 0; i < STATE_COUNT; i ++ ) {
			if ( w[ i ] <= 0 ) continue;
			const c = linear( STATES[ i ][ k ] );
			t[ 0 ] += c[ 0 ] * w[ i ]; t[ 1 ] += c[ 1 ] * w[ i ]; t[ 2 ] += c[ 2 ] * w[ i ];
		}
	}

	for ( const k of VEC_KEYS ) {
		const t = out[ k ];
		t[ 0 ] = t[ 1 ] = t[ 2 ] = 0;
		for ( let i = 0; i < STATE_COUNT; i ++ ) {
			if ( w[ i ] <= 0 ) continue;
			const v = STATES[ i ][ k ];
			t[ 0 ] += v[ 0 ] * w[ i ]; t[ 1 ] += v[ 1 ] * w[ i ]; t[ 2 ] += v[ 2 ] * w[ i ];
		}
	}

	for ( const k of NUM_KEYS ) {
		let v = 0;
		for ( let i = 0; i < STATE_COUNT; i ++ ) if ( w[ i ] > 0 ) v += STATES[ i ][ k ] * w[ i ];
		out[ k ] = v;
	}

	const near = Math.max( 0, Math.min( PHASE_MAX, Math.round( phase ) ) );
	out.accent = STATES[ near ].accent;
	out.name = STATES[ near ].name;
	out.index = near;
	return out;
}
