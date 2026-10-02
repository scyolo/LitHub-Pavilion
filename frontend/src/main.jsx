import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";
import { api } from "./api.js";
import App from "./App.jsx";
import DataSession from "./components/DataSession.jsx";
import "./index.css";

// Warm the shared reader while React constructs the shell.
if (api.isSnapshot) api.directions().catch(() => {});

const Router = api.useHashRouting ? HashRouter : BrowserRouter;

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <DataSession>
      <Router><App /></Router>
    </DataSession>
  </React.StrictMode>
);
