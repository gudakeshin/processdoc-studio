/** @type {import("eslint").Linter.Config[]} */
const nextConfig = require("eslint-config-next");

module.exports = [
  ...nextConfig,
  {
    rules: {
      // react-hooks v7 flags many valid patterns (hydration, fetch kickoff, localStorage).
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/purity": "warn",
    },
  },
];
