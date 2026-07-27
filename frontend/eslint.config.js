/** @type {import("eslint").Linter.Config[]} */
const nextConfig = require("eslint-config-next");

module.exports = [
  ...nextConfig,
  {
    rules: {
      // react-hooks v7 flags many valid patterns (hydration, fetch kickoff, localStorage).
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/purity": "warn",
      // Accessibility rules (jsx-a11y plugin already registered by eslint-config-next)
      "jsx-a11y/alt-text": "error",
      "jsx-a11y/aria-props": "error",
      "jsx-a11y/aria-proptypes": "error",
      "jsx-a11y/aria-unsupported-elements": "error",
      "jsx-a11y/interactive-supports-focus": "error",
      "jsx-a11y/label-has-associated-control": [
        "error",
        { controlComponents: ["Input", "Select", "Textarea"] },
      ],
      "jsx-a11y/no-noninteractive-element-interactions": "error",
      "jsx-a11y/role-has-required-aria-props": "error",
      "jsx-a11y/role-supports-aria-props": "error",
    },
  },
  {
    // The @typescript-eslint plugin is registered by eslint-config-next for TS files only.
    files: ["**/*.ts", "**/*.tsx"],
    rules: {
      // Visibility-only for now; ratchet to "error" once existing `any`s are burned down.
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
];
