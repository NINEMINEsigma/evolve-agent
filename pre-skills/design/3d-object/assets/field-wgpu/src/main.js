/**
 * Entry point: boot the renderer, hand it the scroll, keep the chrome honest.
 */

import { createStage } from './scene/stage.js';
import { createScroll } from './site/scroll.js';
import { STATES } from './scene/palette.js';

const boot = document.getElementById( 'boot' );
const bootNote = document.querySelector( '[data-boot-note]' );
const fallback = document.getElementById( 'fallback' );
const canvas = document.getElementById( 'stage' );

const progressBar = document.querySelector( '[data-progress]' );
const railItems = Array.from( document.querySelectorAll( '[data-rail]' ) );
const hudFps = document.querySelector( '[data-hud="fps"]' );
const hudCount = document.querySelector( '[data-hud="count"]' );
const hudState = document.querySelector( '[data-hud="state"]' );
const countText = Array.from( document.querySelectorAll( '[data-count-text]' ) );

const reducedMotion = window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;

function fail( reason ) {
	boot.classList.add( 'is-done' );
	fallback.hidden = false;
	const slot = document.querySelector( '[data-fallback-reason]' );
	if ( slot && reason ) slot.textContent = String( reason );
	console.error( '[field]', reason );
}

async function start() {

	if ( ! navigator.gpu ) {
		fail( 'navigator.gpu is undefined' );
		return;
	}

	let stage;
	try {
		bootNote.textContent = '正在请求适配器';
		stage = await createStage( canvas, { reducedMotion } );
	} catch ( error ) {
		fail( error && error.message ? error.message : error );
		return;
	}

	const scroll = createScroll( { reducedMotion } );
	const drive = scroll.drive;

	/* first frame: this is where the pipelines actually get built --------- */
	bootNote.textContent = '正在编译管线';
	await new Promise( ( r ) => requestAnimationFrame( r ) );
	stage.frame( 1 / 60, drive );
	await new Promise( ( r ) => requestAnimationFrame( r ) );
	stage.frame( 1 / 60, drive );

	document.body.classList.add( 'is-live' );
	boot.classList.add( 'is-done' );
	scroll.begin();

	/* --- chrome ---------------------------------------------------------- */

	let shownCount = - 1;
	let activeState = - 1;
	let fps = 60;

	function chrome( dt ) {
		fps += ( 1 / Math.max( dt, 0.0001 ) - fps ) * 0.06;

		if ( progressBar ) progressBar.style.width = ( drive.travel * 100 ).toFixed( 2 ) + '%';

		const near = stage.palette.index;
		if ( near !== activeState ) {
			activeState = near;
			railItems.forEach( ( li, i ) => li.classList.toggle( 'is-active', i === near ) );
			document.documentElement.style.setProperty( '--accent', STATES[ near ].accent );
			if ( hudState ) hudState.textContent = STATES[ near ].name;
		}

		if ( stage.instanceCount !== shownCount ) {
			shownCount = stage.instanceCount;
			const pretty = shownCount.toLocaleString( 'en-US' );
			countText.forEach( ( el ) => { el.textContent = pretty; } );
			if ( hudCount ) hudCount.textContent = pretty + ' 草叶';
		}

		if ( hudFps ) hudFps.textContent = Math.round( fps ) + ' fps';
	}

	/* --- loop ------------------------------------------------------------ */

	let last = performance.now();
	window.gsap.ticker.add( () => {
		const now = performance.now();
		const dt = Math.min( ( now - last ) / 1000, 0.1 );
		last = now;

		stage.frame( dt, drive );
		chrome( dt );
	} );

	/* --- input ----------------------------------------------------------- */

	window.addEventListener( 'pointermove', ( e ) => {
		if ( e.pointerType === 'touch' ) return;
		stage.setPointer(
			( e.clientX / window.innerWidth ) * 2 - 1,
			( e.clientY / window.innerHeight ) * 2 - 1
		);
	}, { passive: true } );

	// handle for the console and for the screenshot harness
	window.FIELD = { stage, scroll, drive };

	let resizeTimer = 0;
	window.addEventListener( 'resize', () => {
		stage.resize();
		clearTimeout( resizeTimer );
		resizeTimer = setTimeout( () => scroll.refresh(), 180 );
	} );
}

if ( document.readyState === 'loading' ) {
	window.addEventListener( 'DOMContentLoaded', start, { once: true } );
} else {
	start();
}
