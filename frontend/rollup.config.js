import resolve from "@rollup/plugin-node-resolve";
import terser from "@rollup/plugin-terser";
import typescript from "@rollup/plugin-typescript";

const dev = process.env.ROLLUP_WATCH;

export default {
  input: "src/tile-tracker-card.ts",
  output: {
    file: "../www/tile-tracker-card.js",
    format: "es",
    sourcemap: dev ? "inline" : false,
  },
  plugins: [
    resolve(),
    typescript(),
    !dev && terser({
      format: {
        comments: false,
      },
    }),
  ].filter(Boolean),
};
