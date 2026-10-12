/** Shared character-name color hashing (avatar / round navigation rail). */

export function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const chr = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0;
  }
  return Math.abs(hash);
}

export function hueFromString(str: string): number {
  return hashString(str) % 360;
}
