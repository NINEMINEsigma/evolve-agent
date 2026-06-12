import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/variables.css";
import "./styles/base.css";
import "./styles/sidebar.css";
import "./styles/header.css";
import "./styles/chat.css";
import "./styles/messages.css";
import "./styles/playlist.css";
import "./styles/lightbox.css";
import "./styles/dialogs.css";
import "./styles/panels.css";
import "./styles/drawer.css";
import "./styles/input.css";
import "./styles/context-menu.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);