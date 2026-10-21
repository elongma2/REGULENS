import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { initializeAutoHideScrollbars } from "./lib/scrollbars";
import "./index.css";

const disposeScrollbars = initializeAutoHideScrollbars();
import.meta.hot?.dispose(disposeScrollbars);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter><AuthProvider><App /></AuthProvider></BrowserRouter>
  </StrictMode>,
);
