/*
  api/live.js (repo root): the same function as app/site/api/live.js, for a deployment whose
  root is the repo root.

  Why two files: for a project without a framework, Vercel only builds functions from the
  `api` folder at the project ROOT. The site lives in app/site and asks for the relative path
  "api/live", which is /app/site/api/live when the repo root is deployed. vercel.json rewrites
  that address to /api/live, which is this file. If app/site itself is the deployment root,
  app/site/api/live.js is the root function and this file is simply not used.

  The handler is not copied: it is the one in app/site/api/live.js.
*/
module.exports = require("../app/site/api/live.js");
