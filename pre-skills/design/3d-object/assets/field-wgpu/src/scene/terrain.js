/**
 * The ground. One plane, displaced by the shared height field, shaded four
 * different ways and cross-faded by the same weights that drive the strands:
 * meadow soil, open water, scorched dune, and a quantised lattice floor.
 */

import { Mesh, MeshBasicNodeMaterial, PlaneGeometry } from 'three';
import {
	Fn, vec2, vec3, float, clamp, dot, pow, mix, smoothstep, sin, fract, abs, max, min,
	length, normalize, fwidth, positionGeometry, positionWorld, cameraPosition,
	varying, mx_noise_float, mx_fractal_noise_float
} from 'three/tsl';

import { U } from './uniforms.js';
import { surfaceHeight, surfaceNormal, blendStates, applyFog, GROUND_SIZE } from './tsl-common.js';

const SEGMENTS = 256;

export function createTerrain() {
	const geometry = new PlaneGeometry( GROUND_SIZE, GROUND_SIZE, SEGMENTS, SEGMENTS );
	geometry.rotateX( - Math.PI / 2 );

	const material = new MeshBasicNodeMaterial( { fog: false } );

	material.positionNode = Fn( () => {
		const p = positionGeometry.xz;
		return vec3( p.x, surfaceHeight( p ), p.y );
	} )();

	const vNormal = varying( Fn( () => surfaceNormal( positionGeometry.xz, float( 0.8 ) ) )(), 'v_groundNormal' );

	material.colorNode = Fn( () => {
		const p = positionWorld.xz;
		const N = normalize( vNormal );
		const V = normalize( cameraPosition.sub( positionWorld ) );
		const L = U.sunDir;
		const sun = U.sunColor.mul( U.sunIntensity.mul( 0.30 ) );
		const t = U.time;

		/* --- shared soft lighting ------------------------------------- */
		const ndl = dot( N, L );
		const wrap = clamp( ndl.mul( 0.62 ).add( 0.38 ), 0, 1 );
		const skyLight = U.ambient.mul( U.ambientAmount ).mul( clamp( N.y.mul( 0.5 ).add( 0.5 ), 0, 1 ) );

		/* --- I. meadow soil -------------------------------------------- */
		const meadow = () => {
			const patch = mx_fractal_noise_float( vec3( p.mul( 0.028 ), 2.0 ), 3, 2.0, 0.5 ).mul( 0.5 ).add( 0.5 );
			const grain = mx_noise_float( vec3( p.mul( 0.5 ), 9.0 ) ).mul( 0.5 ).add( 0.5 );
			const base = mix( U.groundColor, U.groundTint, patch.mul( 0.7 ).add( grain.mul( 0.3 ) ) );
			const slope = pow( clamp( N.y, 0, 1 ), 1.5 );
			return base.mul( sun.mul( wrap ).add( skyLight ) ).mul( slope.mul( 0.55 ).add( 0.45 ) );
		};

		/* --- II. open water -------------------------------------------- */
		const tide = () => {
			const rp = p.mul( 1.15 );
			const r1 = mx_noise_float( vec3( rp.add( vec2( t.mul( 0.42 ), t.mul( 0.27 ) ) ), t.mul( 0.22 ) ) );
			const r2 = mx_noise_float( vec3( rp.mul( 2.9 ).add( vec2( t.mul( - 0.55 ), t.mul( 0.36 ) ) ), t.mul( 0.31 ) ) );
			const nrm = normalize( N.add( vec3( r1.mul( 0.30 ), 0, r2.mul( 0.30 ) ) ) );

			const ndh = clamp( dot( nrm, normalize( L.add( V ) ) ), 0, 1 );
			const spec = pow( ndh, 300.0 ).mul( 4.6 ).add( pow( ndh, 24.0 ).mul( 0.22 ) );
			const fres = pow( clamp( float( 1 ).sub( dot( nrm, V ) ), 0, 1 ), 4.0 );

			const deep = U.groundColor.mul( sun.mul( 0.32 ).add( skyLight ) );
			const body = mix( deep, U.groundTint.mul( 0.5 ), clamp( r1.mul( 0.5 ).add( 0.5 ), 0, 1 ).mul( 0.45 ) );
			// the reflection is the sky overhead almost everywhere, and only
			// turns warm where the surface actually points back at the sun
			const skyRefl = mix( U.skyZenith.mul( 1.6 ), U.skyHorizon.mul( 0.9 ), pow( ndh, 3.0 ) );
			const reflected = mix( body, skyRefl, clamp( fres.mul( 0.8 ), 0, 1 ) );
			const crest = smoothstep( 0.965, 0.82, N.y );

			return reflected
				.add( U.sunColor.mul( U.sunIntensity ).mul( spec ) )
				.add( vec3( 0.30, 0.46, 0.55 ).mul( crest.mul( 0.4 ) ) );
		};

		/* --- III. scorched dune ---------------------------------------- */
		const ember = () => {
			const grit = mx_noise_float( vec3( p.mul( 0.85 ), 3.0 ) ).mul( 0.5 ).add( 0.5 );
			const base = U.groundColor.mul( grit.mul( 0.55 ).add( 0.75 ) ).mul( sun.mul( wrap ).add( skyLight ) );

			const veins = mx_fractal_noise_float( vec3( p.mul( 0.022 ), 7.0 ), 3, 2.0, 0.5 );
			const d = abs( veins );
			const aa = max( fwidth( d ), 0.0015 );
			const crack = float( 1 ).sub( smoothstep( 0.0, aa.mul( 2.0 ).add( 0.013 ), d ) );
			const breathe = sin( t.mul( 1.15 ).add( p.x.mul( 0.06 ) ).add( p.y.mul( 0.04 ) ) ).mul( 0.28 ).add( 0.72 );
			const flat = smoothstep( 0.45, 0.92, N.y );

			return base.add( U.groundTint.mul( 4.5 ).mul( crack ).mul( breathe ).mul( flat ) );
		};

		/* --- IV. lattice floor ------------------------------------------ */
		const lattice = () => {
			const g = p.div( 2.6 );
			const dl = min(
				float( 0.5 ).sub( abs( fract( g.x ).sub( 0.5 ) ) ),
				float( 0.5 ).sub( abs( fract( g.y ).sub( 0.5 ) ) )
			);
			const line = float( 1 ).sub( smoothstep( 0.0, max( fwidth( dl ), 0.002 ).mul( 2.2 ), dl ) );

			const gm = p.div( 20.8 );
			const dm = min(
				float( 0.5 ).sub( abs( fract( gm.x ).sub( 0.5 ) ) ),
				float( 0.5 ).sub( abs( fract( gm.y ).sub( 0.5 ) ) )
			);
			const lineMajor = float( 1 ).sub( smoothstep( 0.0, max( fwidth( dm ), 0.002 ).mul( 2.2 ), dm ) );

			const ring = fract( length( p ).mul( 0.016 ).sub( t.mul( 0.07 ) ) );
			const pulse = pow( float( 1 ).sub( ring ), 8.0 );

			const base = U.groundColor.mul( skyLight.add( sun.mul( 0.1 ) ) );
			const glow = U.groundTint
				.mul( line.mul( 0.42 ).add( lineMajor.mul( 1.15 ) ) )
				.mul( pulse.mul( 1.7 ).add( 0.34 ) );
			return base.add( glow );
		};

		const col = blendStates( [ meadow, tide, ember, lattice ], 'vec3' );
		return applyFog( max( col, vec3( 0 ) ) );
	} )();

	const mesh = new Mesh( geometry, material );
	mesh.frustumCulled = false;
	mesh.name = 'terrain';
	return mesh;
}
