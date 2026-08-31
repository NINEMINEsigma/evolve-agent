/**
 * Scroll choreography.
 *
 * The page produces exactly two numbers for the scene: `travel` (0..1 down the
 * document) and `phase` (0..3, which state the field is in). Everything else —
 * camera, colour, bloom — is derived from those inside the renderer.
 */

import Lenis from '../../vendor/lenis/lenis.mjs';

const { gsap, ScrollTrigger, SplitText } = window;

const clamp01 = ( v ) => ( v < 0 ? 0 : v > 1 ? 1 : v );
const smooth = ( t ) => t * t * ( 3 - 2 * t );

export function createScroll( { reducedMotion = false } = {} ) {

	gsap.registerPlugin( ScrollTrigger, SplitText );

	/* --- real scroll, just eased. Keeps position:sticky honest. --------- */
	const lenis = reducedMotion ? null : new Lenis( {
		duration: 1.05,
		easing: ( t ) => Math.min( 1, 1.001 - Math.pow( 2, - 10 * t ) ),
		smoothWheel: true,
		syncTouch: false,
		touchMultiplier: 1.6
	} );

	if ( lenis ) {
		lenis.on( 'scroll', ScrollTrigger.update );
		gsap.ticker.add( ( time ) => lenis.raf( time * 1000 ) );
		gsap.ticker.lagSmoothing( 0 );
	}

	/* --- phase mapping -------------------------------------------------- */

	const chapters = Array.from( document.querySelectorAll( '[data-chapter]' ) );
	const drive = { travel: 0, phase: 0 };
	let marks = [];

	function measure() {
		const total = ScrollTrigger.maxScroll( window ) || 1;
		marks = chapters.map( ( el ) => {
			const box = el.getBoundingClientRect();
			const top = box.top + window.scrollY;
			return {
				reach: ( top + el.offsetHeight * 0.22 ) / total,
				hold: ( top + el.offsetHeight * 0.62 ) / total
			};
		} );
		update( window.scrollY / total );
	}

	function phaseAt( t ) {
		if ( marks.length === 0 ) return 0;
		if ( t <= marks[ 0 ].hold ) return 0;
		for ( let i = 0; i < marks.length - 1; i ++ ) {
			const a = marks[ i ].hold;
			const b = marks[ i + 1 ].reach;
			if ( t < b ) return i + smooth( clamp01( ( t - a ) / Math.max( b - a, 1e-6 ) ) );
			if ( t < marks[ i + 1 ].hold ) return i + 1;
		}
		return marks.length - 1;
	}

	function update( t ) {
		drive.travel = clamp01( t );
		drive.phase = phaseAt( drive.travel );
	}

	ScrollTrigger.create( {
		trigger: 'main',
		start: 'top top',
		end: 'bottom bottom',
		onUpdate: ( self ) => update( self.progress )
	} );

	ScrollTrigger.addEventListener( 'refreshInit', () => { marks = []; } );
	ScrollTrigger.addEventListener( 'refresh', measure );
	measure();

	/* --- copy reveals --------------------------------------------------- */

	function splitLines( el ) {
		try {
			return SplitText.create( el, { type: 'lines', mask: 'lines', linesClass: 'split-line' } ).lines;
		} catch ( e ) {
			return [ el ];
		}
	}

	function revealsFor( scope, useScrollTrigger ) {
		const items = [];
		scope.querySelectorAll( '[data-reveal-lines]' ).forEach( ( el ) => {
			const lines = splitLines( el );
			items.push( { targets: lines, from: { yPercent: 118, opacity: 0 }, stagger: 0.08, trigger: el } );
		} );
		scope.querySelectorAll( '[data-reveal]' ).forEach( ( el ) => {
			items.push( { targets: el, from: { y: 24, opacity: 0 }, stagger: 0, trigger: el } );
		} );

		if ( ! useScrollTrigger ) return items;

		items.forEach( ( it ) => {
			gsap.from( it.targets, {
				...it.from,
				duration: 1.35,
				ease: 'expo.out',
				stagger: it.stagger,
				scrollTrigger: { trigger: it.trigger, start: 'top 90%', once: true }
			} );
		} );
		return items;
	}

	/** Call once the renderer has a frame on screen. */
	function begin() {
		const hero = document.querySelector( '.hero' );
		const heroItems = revealsFor( hero, false );

		const tl = gsap.timeline( { defaults: { duration: 1.5, ease: 'expo.out' } } );
		heroItems.forEach( ( it, i ) => {
			tl.from( it.targets, { ...it.from, stagger: it.stagger }, i === 0 ? 0 : `-=1.22` );
		} );

		document.querySelectorAll( '.chapter, .outro' ).forEach( ( el ) => revealsFor( el, true ) );
		ScrollTrigger.refresh();
	}

	return { drive, begin, lenis, refresh: () => ScrollTrigger.refresh() };
}
