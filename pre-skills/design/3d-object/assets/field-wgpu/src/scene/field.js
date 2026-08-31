/**
 * The field: one instanced strand, drawn a few hundred thousand times.
 *
 * A compute pass rewrites four storage buffers every frame — root, axis, tint,
 * misc — describing what each strand currently *is*. The vertex stage does
 * nothing but bend a 12-vertex ribbon according to those numbers. Changing
 * state never touches geometry; it only changes what the compute pass writes.
 *
 *   I   meadow   upright blade, wind-bent, rooted in the soil
 *   II  tide     laid flat along the wave gradient, foam on the crests
 *   III ember    cut loose, rising and cooling
 *   IV  lattice  snapped to a grid, quantised, lit from within
 */

import { DoubleSide, Float32BufferAttribute, InstancedBufferGeometry, Mesh, MeshBasicNodeMaterial } from 'three';
import {
	Fn, If, instanceIndex, instancedArray, uv, vec2, vec3, vec4, float, sin, cos, sign,
	pow, mix, clamp, smoothstep, step, fract, round, abs, max, length, normalize,
	dot, cross, varying, positionWorld, cameraPosition, mx_fractal_noise_float, mx_cell_noise_float
} from 'three/tsl';

import { U } from './uniforms.js';
import { linear } from './palette.js';
import { rnd, stateWeights, surfaceHeight, windAt, applyFog, FIELD_RADIUS } from './tsl-common.js';

const TAU = 6.283185307179586;
const GOLDEN = 2.399963229728653;

const col = ( hex ) => { const c = linear( hex ); return vec3( c[ 0 ], c[ 1 ], c[ 2 ] ); };

const GRASS_DARK = col( '#1d3a12' );
const GRASS_LIGHT = col( '#7f9a35' );
const GRASS_DRY = col( '#b39a4e' );
const FLOWER = col( '#ffe4b8' );

const FOAM = col( '#cfeaf5' );

const EMBER_HOT = col( '#ffd08a' );
const EMBER_MID = col( '#ff6a1c' );
const EMBER_COLD = col( '#5c1105' );

const FILAMENT = col( '#9fecff' );
const FILAMENT_HOT = col( '#ffffff' );

/* ------------------------------------------------------------- geometry */

function strandGeometry( segments ) {
	const position = [];
	const uvs = [];
	const index = [];

	for ( let i = 0; i <= segments; i ++ ) {
		const t = i / segments;
		position.push( - 0.5, t, 0, 0.5, t, 0 );
		uvs.push( 0, t, 1, t );
	}
	for ( let i = 0; i < segments; i ++ ) {
		const a = i * 2, b = a + 1, c = a + 2, d = a + 3;
		index.push( a, b, c, b, d, c );
	}

	const geometry = new InstancedBufferGeometry();
	geometry.setAttribute( 'position', new Float32BufferAttribute( position, 3 ) );
	geometry.setAttribute( 'uv', new Float32BufferAttribute( uvs, 2 ) );
	geometry.setIndex( index );
	return geometry;
}

/* ---------------------------------------------------------------- field */

export function createField( { count = 200000, segments = 5 } = {} ) {

	const sRoot = instancedArray( count, 'vec4' ); // xyz root, w height
	const sAxis = instancedArray( count, 'vec4' ); // xy facing, z total tilt, w width
	const sTint = instancedArray( count, 'vec4' ); // rgb colour, a emission
	const sMisc = instancedArray( count, 'vec4' ); // x tip gain, y root darken, z sheen, w unused

	/* ------------------------------------------------------ compute pass */

	const update = Fn( () => {

		const id = instanceIndex;
		const fi = id.toFloat();
		const r0 = rnd( id, 0 ), r1 = rnd( id, 1 ), r2 = rnd( id, 2 );
		const r3 = rnd( id, 3 ), r4 = rnd( id, 4 ), r5 = rnd( id, 5 );

		// Vogel disc. `skip` holds the innermost ring away from the lens —
		// without it a handful of strands land centimetres from the camera and
		// fill the frame.
		const skip = float( Math.max( 600, count * 0.004 ) );
		const seq = fi.add( skip ).div( float( count ).add( skip ) );
		const ang = fi.mul( GOLDEN ).add( r0.mul( 0.9 ) );
		const bearing = vec2( cos( ang ), sin( ang ) );
		const scatter = vec2( r1.sub( 0.5 ), r2.sub( 0.5 ) );

		/**
		 * exponent 0.5 spreads the disc evenly; higher values pull density
		 * toward the camera. Grass wants the bias (near blades matter most);
		 * embers and filaments want the even spread or they become a curtain
		 * hanging off the lens.
		 */
		const place = ( exponent, radius ) => {
			const rad = pow( seq, exponent ).mul( radius );
			return { rad, p: bearing.mul( rad ).add( scatter.mul( rad.mul( 0.06 ).add( 0.12 ) ) ) };
		};

		const gust = float( 1 ).add( U.warp.mul( 1.6 ) );
		const t = U.time;

		const root = vec3( 0 ).toVar();
		const height = float( 0 ).toVar();
		const facing = vec2( 0 ).toVar();
		const tilt = float( 0 ).toVar();
		const width = float( 0 ).toVar();
		const tint = vec3( 0 ).toVar();
		const emit = float( 0 ).toVar();
		const tipGain = float( 0 ).toVar();
		const rootDark = float( 0 ).toVar();
		const sheen = float( 0 ).toVar();

		const w = stateWeights();

		/* --- I. meadow ------------------------------------------------- */
		If( w[ 0 ].greaterThan( 0.0005 ), () => {
			const k = w[ 0 ];
			const p = place( 0.78, FIELD_RADIUS ).p;
			const wind = windAt( p );

			const clump = mx_fractal_noise_float( vec3( p.mul( 0.055 ), 13.0 ), 2, 2.0, 0.5 ).mul( 0.5 ).add( 0.5 );
			const dry = mx_fractal_noise_float( vec3( p.mul( 0.021 ), 31.0 ), 2, 2.0, 0.5 ).mul( 0.5 ).add( 0.5 );

			const h = mix( 0.55, 1.7, r3 ).mul( clump.mul( 0.5 ).add( 0.68 ) );
			const flutter = sin( t.mul( 2.8 ).add( r0.mul( 61.0 ) ).add( p.x.mul( 0.55 ) ) ).mul( 0.1 );
			const sway = wind.z.mul( 0.55 ).add( flutter ).mul( gust );

			const own = vec2( cos( r1.mul( TAU ) ), sin( r1.mul( TAU ) ) );
			const dir = normalize( mix( own, wind.xy, clamp( wind.z.mul( 0.8 ), 0.2, 0.9 ) ).add( vec2( 0.0001 ) ) );

			const blade = mix( GRASS_DARK, GRASS_LIGHT, r3.mul( 0.65 ).add( clump.mul( 0.35 ) ) );
			const withDry = mix( blade, GRASS_DRY, pow( dry, 2.2 ).mul( 0.75 ) );
			const isFlower = step( 0.9985, r4 );
			const colour = mix( withDry, FLOWER, isFlower );

			root.addAssign( vec3( p.x, surfaceHeight( p ), p.y ).mul( k ) );
			height.addAssign( h.mul( k ) );
			facing.addAssign( dir.mul( k ) );
			tilt.addAssign( float( 0.2 ).add( sway.mul( 0.85 ) ).mul( k ) );
			width.addAssign( float( 0.026 ).add( r4.mul( 0.016 ) ).add( isFlower.mul( 0.02 ) ).mul( k ) );
			tint.addAssign( colour.mul( k ) );
			emit.addAssign( isFlower.mul( 0.2 ).mul( k ) );
			tipGain.addAssign( float( 1.55 ).mul( k ) );
			rootDark.addAssign( float( 0.22 ).mul( k ) );
			sheen.addAssign( float( 0.5 ).mul( k ) );
		} );

		/* --- II. tide -------------------------------------------------- */
		If( w[ 1 ].greaterThan( 0.0005 ), () => {
			const k = w[ 1 ];
			const p = place( 0.68, 170 ).p;
			const gy = surfaceHeight( p ).toVar();

			const e = float( 1.1 );
			const gx = surfaceHeight( p.add( vec2( e, 0 ) ) ).sub( surfaceHeight( p.sub( vec2( e, 0 ) ) ) );
			const gz = surfaceHeight( p.add( vec2( 0, e ) ) ).sub( surfaceHeight( p.sub( vec2( 0, e ) ) ) );
			// foam runs along the crest, i.e. perpendicular to the slope
			const flow = normalize( vec2( gz.negate(), gx ).add( vec2( 0.0001 ) ) );

			// only the crests carry foam — everything else shrinks to nothing
			const crest = smoothstep( 0.3, 1.7, gy ).mul( step( 0.42, r5 ) );
			const h = mix( 0.5, 1.4, r3 ).mul( pow( crest, 1.2 ) );

			root.addAssign( vec3( p.x, gy.add( 0.03 ), p.y ).mul( k ) );
			height.addAssign( h.mul( k ) );
			facing.addAssign( flow.mul( k ) );
			tilt.addAssign( float( 1.47 ).add( r4.mul( 0.1 ) ).mul( k ) );
			width.addAssign( float( 0.07 ).add( r4.mul( 0.07 ) ).mul( pow( crest, 0.6 ) ).mul( k ) );
			tint.addAssign( mix( FOAM.mul( 0.45 ), FOAM, crest ).mul( k ) );
			emit.addAssign( pow( crest, 2.0 ).mul( 0.7 ).mul( k ) );
			tipGain.addAssign( float( 1.2 ).mul( k ) );
			rootDark.addAssign( float( 0.6 ).mul( k ) );
			sheen.addAssign( float( 1.4 ).mul( k ) );
		} );

		/* --- III. ember ------------------------------------------------ */
		If( w[ 2 ].greaterThan( 0.0005 ), () => {
			const k = w[ 2 ];
			const spot = place( 0.5, 195 );
			const wind = windAt( spot.p );
			const alive = step( 0.85, r5 );

			const speed = mix( 0.03, 0.08, r1 );
			const life = fract( r0.add( t.mul( speed ) ) );
			const swirl = life.mul( 5.5 ).add( r3.mul( TAU ) );
			const drift = vec2( sin( swirl ), cos( swirl.mul( 0.77 ) ) ).mul( life.mul( 4.0 ).add( 0.2 ) )
				.add( wind.xy.mul( life.mul( 8.0 ) ) );

			const p = spot.p.add( drift );
			const rise = life.mul( 18.0 ).add( r2.mul( 0.5 ) );
			const pos = vec3( p.x, surfaceHeight( p ).add( rise ), p.y );
			const fade = smoothstep( 0.0, 0.06, life ).mul( smoothstep( 1.0, 0.7, life ) ).mul( alive );

			// sparks are sized in screen space, not world space — otherwise the
			// near ones read as big flat blades instead of points of light
			const grow = clamp( length( pos.sub( U.camPos ) ).mul( 0.0055 ), 0.05, 0.5 );

			const heat = pow( float( 1 ).sub( life ), 1.6 );
			const colour = mix( mix( EMBER_COLD, EMBER_MID, heat ), EMBER_HOT, pow( heat, 3.0 ) );

			root.addAssign( pos.mul( k ) );
			height.addAssign( mix( 1.1, 2.1, r3 ).mul( grow ).mul( fade ).mul( k ) );
			facing.addAssign( normalize( U.camPos.xz.sub( p ).add( vec2( 0.0001 ) ) ).mul( k ) );
			tilt.addAssign( float( 0.02 ).mul( k ) );
			width.addAssign( mix( 0.7, 1.4, r4 ).mul( grow ).mul( fade ).mul( k ) );
			tint.addAssign( colour.mul( k ) );
			emit.addAssign( heat.mul( 1.9 ).add( 0.2 ).mul( fade ).mul( k ) );
			tipGain.addAssign( float( 1.0 ).mul( k ) );
			rootDark.addAssign( float( 1.0 ).mul( k ) );
			sheen.addAssign( float( 0.0 ).mul( k ) );
		} );

		/* --- IV. lattice ------------------------------------------------ */
		If( w[ 3 ].greaterThan( 0.0005 ), () => {
			const k = w[ 3 ];
			const cell = float( 1.9 );
			const g = round( place( 0.5, 178 ).p.div( cell ) ).mul( cell );

			// whether a cell is lit is a property of the cell, not of the strand —
			// so every strand that lands there agrees, and the grid reads as a grid
			const lit = step( 0.55, mx_cell_noise_float( vec3( g.mul( 0.53 ), 7.0 ) ) );
			const keep = lit.mul( step( 0.72, r5 ) );

			const q = round( mx_fractal_noise_float( vec3( g.mul( 0.012 ), 41.0 ), 3, 2.0, 0.5 ).mul( 0.5 ).add( 0.5 ).mul( 5.0 ) ).div( 5.0 );
			const h = float( 0.35 ).add( pow( q, 1.3 ).mul( 8.5 ) ).mul( keep );

			const ring = fract( length( g ).mul( 0.016 ).sub( t.mul( 0.07 ) ) );
			const pulse = pow( float( 1 ).sub( ring ), 9.0 );

			root.addAssign( vec3( g.x, surfaceHeight( g ), g.y ).mul( k ) );
			height.addAssign( h.mul( k ) );
			facing.addAssign( vec2( 0.7071, 0.7071 ).mul( k ) );
			tilt.addAssign( float( 0.015 ).mul( k ) );
			width.addAssign( float( 0.06 ).mul( keep ).mul( k ) );
			tint.addAssign( mix( FILAMENT, FILAMENT_HOT, pulse.mul( 0.8 ) ).mul( k ) );
			emit.addAssign( pulse.mul( 1.6 ).add( 0.45 ).mul( keep ).mul( k ) );
			tipGain.addAssign( float( 1.7 ).mul( k ) );
			rootDark.addAssign( float( 0.3 ).mul( k ) );
			sheen.addAssign( float( 0.0 ).mul( k ) );
		} );

		// clamped so a single unlucky blend can never produce a strand that
		// stretches across the whole frame
		sRoot.element( id ).assign( vec4( root, clamp( height, 0.0, 14.0 ) ) );
		sAxis.element( id ).assign( vec4(
			normalize( facing.add( vec2( 0.0001, 0.00007 ) ) ),
			clamp( tilt, 0.004, 2.2 ),
			clamp( width, 0.0, 0.35 )
		) );
		sTint.element( id ).assign( vec4( tint, emit ) );
		sMisc.element( id ).assign( vec4( tipGain, rootDark, sheen, 0 ) );

	} );

	const computeNode = update().compute( count );

	/* -------------------------------------------------------- rendering */

	const material = new MeshBasicNodeMaterial( { side: DoubleSide, fog: false } );

	// vertex: bend a ribbon along an arc of constant curvature.
	// Plain composition rather than Fn() — it yields several values, and none
	// of it needs control flow.
	const S = ( () => {
		const id = instanceIndex;
		const R = sRoot.element( id );
		const A = sAxis.element( id );
		const T = sTint.element( id );
		const M = sMisc.element( id );

		const t = uv().y;
		const side = uv().x.sub( 0.5 );

		const theta = A.z.mul( t );
		const k = R.w.div( max( A.z, 0.001 ) );
		const up = sin( theta ).mul( k );
		const out = float( 1 ).sub( cos( theta ) ).mul( k );

		const dir = A.xy;
		const across = vec3( dir.y.negate(), 0, dir.x );
		const taper = float( 1 ).sub( pow( t, 2.4 ) ).mul( 0.94 ).add( 0.06 );

		const position = vec3( R.x.add( dir.x.mul( out ) ), R.y.add( up ), R.z.add( dir.y.mul( out ) ) )
			.add( across.mul( side.mul( A.w.mul( taper ) ) ) );

		const tangent = vec3( dir.x.mul( sin( theta ) ), cos( theta ), dir.y.mul( sin( theta ) ) );
		// rounding the cross-section: rotate the face normal toward the edges
		const normal = normalize( mix( normalize( cross( across, tangent ) ), across, side.mul( 1.15 ) ) );

		const colour = T.xyz.mul( mix( M.y, M.x, pow( t, 0.85 ) ) );

		return { position, normal, colour, emit: T.w, sheen: M.z, t };
	} )();

	material.positionNode = S.position;

	const vNormal = varying( S.normal, 'v_strandNormal' );
	const vColour = varying( S.colour, 'v_strandColour' );
	const vExtra = varying( vec3( S.emit, S.sheen, S.t ), 'v_strandExtra' );

	material.colorNode = Fn( () => {
		const V = normalize( cameraPosition.sub( positionWorld ) );
		const n0 = normalize( vNormal );
		const N = n0.mul( sign( dot( n0, V ) ) );
		const L = U.sunDir;

		const sun = U.sunColor.mul( U.sunIntensity.mul( 0.4 ) );
		const ndl = dot( N, L );
		const wrapped = clamp( ndl.mul( 0.5 ).add( 0.5 ), 0, 1 );
		const ambient = U.ambient.mul( U.ambientAmount ).mul( clamp( N.y.mul( 0.35 ).add( 0.65 ), 0, 1 ) );

		// backlit translucency — the whole reason grass reads at golden hour
		const back = clamp( dot( L, V.negate() ), 0, 1 );
		const through = pow( back, 3.0 ).mul( clamp( float( 1 ).sub( abs( ndl ) ), 0, 1 ).mul( 0.55 ).add( 0.45 ) );

		const H = normalize( L.add( V ) );
		const spec = pow( clamp( dot( N, H ), 0, 1 ), 42.0 ).mul( vExtra.y );

		const base = vColour;
		const lit = base.mul( sun.mul( wrapped ).add( ambient ) )
			.add( base.mul( sun ).mul( through.mul( U.translucency ) ) )
			.add( U.sunColor.mul( spec.mul( 0.6 ) ) )
			.add( base.mul( vExtra.x ) );

		return applyFog( max( lit, vec3( 0 ) ) );
	} )();

	const geometry = strandGeometry( segments );
	geometry.instanceCount = count;

	const mesh = new Mesh( geometry, material );
	mesh.frustumCulled = false;
	mesh.name = 'field';

	return {
		mesh,
		computeNode,
		count,
		/** Cheap LOD: draw fewer instances without rebuilding anything. */
		setVisibleCount( n ) {
			geometry.instanceCount = Math.max( 1, Math.min( count, Math.floor( n ) ) );
		}
	};
}
