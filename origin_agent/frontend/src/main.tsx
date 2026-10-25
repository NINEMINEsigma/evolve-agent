import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { configureMonacoEnvironment } from "./services/monacoEnvironment";
import "./styles/variables.css";
import "./styles/base.css";
import "./styles/splash.css";
import "./styles/skeleton.css";
import "./styles/sidebar.css";
import "./styles/header.css";
import "./styles/chat.css";
import "./styles/round-nav.css";
import "./styles/agent-stage.css";
import "./styles/chat-style-scope.css";
import "./styles/messages.css";
import "./styles/lightbox.css";
import "./styles/modal.css";
import "./styles/dialogs.css";
import "./styles/panels.css";
import "./styles/drawer.css";
import "./styles/tabs.css";
import "./styles/activity-dashboard.css";
import "./styles/session-variables.css";
import "./styles/session-media.css";
import "./styles/session-file-changes.css";
import "./styles/session-export.css";
import "./styles/input.css";
import "./styles/morph.css";
import "./styles/tooltip.css";
import "./styles/popup.css";
import "./styles/context-menu.css";
import "./styles/onboarding.css";

configureMonacoEnvironment();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);