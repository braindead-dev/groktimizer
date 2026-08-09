import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { promisify } from "node:util";
import { config as loadDotenv } from "dotenv";

const execFileAsync = promisify(execFile);

export function controlPlaneRoot() {
  if (process.env.GTZ_ROOT) return process.env.GTZ_ROOT;
  const cwd = process.cwd();
  if (existsSync(resolve(cwd, "groktimizer.toml"))) return cwd;
  if (existsSync(resolve(cwd, "..", "groktimizer.toml"))) return resolve(cwd, "..");
  return resolve(cwd, "..");
}

export function hasControlPlaneConfig() {
  loadControlPlaneEnv();
  return existsSync(resolve(controlPlaneRoot(), "groktimizer.toml"));
}

export function uvExecutable() {
  loadControlPlaneEnv();
  return process.env.GTZ_UV_BIN ?? "uv";
}

export async function runGtz(args: string[], timeout = 20_000) {
  loadControlPlaneEnv();
  const { stdout } = await execFileAsync(uvExecutable(), ["run", "gtz", ...args], {
    cwd: controlPlaneRoot(),
    timeout,
    maxBuffer: 2 * 1024 * 1024,
    env: process.env,
  });
  return stdout;
}

export function isSandboxName(value: string) {
  return /^gtz-[a-z0-9]{1,24}-[a-z0-9]{1,24}-[a-z0-9]{1,24}$/.test(value);
}

let loadedEnvRoot: string | null = null;

function loadControlPlaneEnv() {
  const root = controlPlaneRoot();
  if (loadedEnvRoot === root) return;
  loadDotenv({ path: resolve(root, ".env"), override: false, quiet: true });
  loadedEnvRoot = root;
}
