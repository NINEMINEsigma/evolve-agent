// Start the built web player without assuming any Gateway or fixed port.
// PROMO_WEB_PORT may provide a temporary port; otherwise the OS selects an available one.
import {spawn} from "node:child_process";
import net from "node:net";

const requested = Number(process.env.PROMO_WEB_PORT || 0);
const host = process.env.PROMO_WEB_HOST || "127.0.0.1";
const root = "out/web";

const reserve = net.createServer();
reserve.listen({host, port: Number.isFinite(requested) ? requested : 0}, () => {
  const address = reserve.address();
  const port = typeof address === "object" && address ? address.port : requested;
  reserve.close(() => {
    console.log(`视频播放器地址：http://${host}:${port}/`);
    const command = process.platform === "win32" ? "npx.cmd" : "npx";
    const child = spawn(command, ["-y", "http-server", root, "-p", String(port), "-a", host, "-c-1"], {
      stdio: "inherit",
      shell: process.platform === "win32",
      env: process.env,
    });
    child.on("close", (code, signal) => {
      process.exitCode = code ?? (signal ? 1 : 0);
    });
    child.on("error", (error) => {
      console.error(`启动网页服务失败：${error.message}`);
      process.exitCode = 1;
    });
  });
});
reserve.on("error", (error) => {
  console.error(`端口不可用：${error.message}`);
  process.exitCode = 1;
});
