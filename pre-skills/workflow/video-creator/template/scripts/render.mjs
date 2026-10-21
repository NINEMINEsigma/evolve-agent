// Windows-safe Remotion renderer: creates out/, mirrors logs, and propagates the child exit code.
import {spawn} from "node:child_process";
import fs from "node:fs";
import path from "node:path";

fs.mkdirSync("out", {recursive: true});
const scaleArg = process.argv.find((x) => x.startsWith("--scale="));
const scale = scaleArg ? Number(scaleArg.split("=")[1]) : 1;
const preview = process.argv.includes("--preview");
const composition = preview ? "PromoPreview" : "Promo";
const dest = preview ? "out/preview.mp4" : scale === 2 ? "out/final-4k.mp4" : "out/final-1080p.mp4";
const cli = path.resolve("node_modules/@remotion/cli/remotion-cli.js");
const log = fs.createWriteStream("out/render.log", {encoding: "utf8"});
const args = [cli, "render", composition, dest, `--scale=${preview ? 0.5 : scale}`, "--concurrency=4", "--crf=17", "--codec=h264", "--audio-codec=aac", "--audio-bitrate=192k", "--log=info"];
if (process.env.PROMO_BROWSER_EXECUTABLE) args.push(`--browser-executable=${process.env.PROMO_BROWSER_EXECUTABLE}`);
const child = spawn(process.execPath, args, {stdio: ["ignore", "pipe", "pipe"], shell: false});
child.stdout.on("data", (data) => { process.stdout.write(data); log.write(data); });
child.stderr.on("data", (data) => { process.stderr.write(data); log.write(data); });
child.on("error", (error) => { console.error(error); log.end(); process.exitCode = 1; });
child.on("close", (code) => { log.end(); process.exitCode = code ?? 1; });
