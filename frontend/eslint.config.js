// Flat config. tsc still does type-checking (npm run lint runs both); ESLint here
// is for the things the compiler does not catch — hook dependency lists, a11y on
// interactive elements, dead code. Prettier owns formatting, so its rules are
// disabled here via eslint-config-prettier.

import js from "@eslint/js";
import a11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";
import prettier from "eslint-config-prettier";

export default tseslint.config(
  { ignores: ["dist/", "coverage/", "node_modules/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      "react-hooks": reactHooks,
      "jsx-a11y": a11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...a11y.flatConfigs.recommended.rules,
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // The codebase uses leading-underscore module privates deliberately.
      "@typescript-eslint/no-non-null-assertion": "off",
      // Every data view here follows the same idiom: clear the error and fire the
      // fetch from an effect keyed on its inputs. That is exactly what an effect is
      // for; this experimental rule flags it as a cascading-render risk it is not.
      // rules-of-hooks and exhaustive-deps (the ones that catch real bugs) stay on.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["**/*.test.{ts,tsx}", "src/test/**", "scripts/**"],
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
  prettier,
);
