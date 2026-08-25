"use strict";

// preload - the only bridge between renderer pages and Node.
// Runs with sandbox:false + contextIsolation:true so it can require our
// own pure-JS project library while pages stay fully sandboxed.

const { contextBridge, ipcRenderer } = require("electron");
const project = require("./lib/project.js");

const invoke = (ch, ...args) => ipcRenderer.invoke(ch, ...args);

contextBridge.exposeInMainWorld("riley", {
  get: (p) => invoke("api:get", p),
  post: (p, body) => invoke("api:post", p, body),
  fileUrl: (rel) => invoke("file:url", rel),
  saveProject: (arg) => invoke("project:save", arg),
  openProject: () => invoke("project:open"),
  openWin: (name) => invoke("win:open", name),
  engineInfo: () => invoke("engine:info"),
  project: {
    emptyProject: project.emptyProject,
    validateProject: project.validateProject,
    serialize: project.serialize,
    parse: project.parse,
    SCHEMA_VERSION: project.SCHEMA_VERSION,
  },
});
