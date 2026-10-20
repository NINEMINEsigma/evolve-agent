import { createRoot } from "react-dom/client";
import fonts from "../fonts.json";
import { App } from "./App";
import { WEB } from "./config";
import "./style.css";

Promise.all(fonts.fonts.map(async (font) => {
  const face = new FontFace(font.family, `url(./fonts/${font.file}.woff2)`, {weight: font.weight});
  document.fonts.add(await face.load());
})).then(() => {
  document.title = WEB.title;
  createRoot(document.getElementById("root")!).render(<App />);
}).catch((error) => {
  document.getElementById("root")!.textContent = `字体加载失败：${String(error)}`;
});
