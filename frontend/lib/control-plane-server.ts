import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { promisify } from "node:util";
import { config as loadDotenv } from "dotenv";
import type { BaselineSnapshot } from "@/lib/control-plane-types";

const execFileAsync = promisify(execFile);

export function controlPlaneRoot() {
  return process.env.GTZ_ROOT ?? resolve(process.cwd(), "..");
}

export function hasControlPlaneConfig() {
  return existsSync(resolve(controlPlaneRoot(), "groktimizer.toml"));
}

export function uvExecutable() {
  return process.env.GTZ_UV_BIN ?? "uv";
}

export async function runGtz(args: string[], timeout = 20_000) {
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

interface RawBenchResult {
  ttft_ms: number;
  decode_tps: number;
  prefill_tps: number;
}

interface RawThroughputResult {
  concurrency: number;
  agg_decode_tps: number;
  per_stream_tps: number;
  median_ttft_ms: number;
  e2e_tps: number;
}

interface RawAccuracyResult {
  task: string;
  correct: number;
  total: number;
  acc: number;
  unparsed: number;
}

let baselineCache: { expiresAt: number; value: BaselineSnapshot } | null = null;
let loadedEnvRoot: string | null = null;

function loadControlPlaneEnv() {
  const root = controlPlaneRoot();
  if (loadedEnvRoot === root) return;
  loadDotenv({ path: resolve(root, ".env"), override: false, quiet: true });
  loadedEnvRoot = root;
}

function configuredSharedRepo() {
  const config = readFileSync(resolve(controlPlaneRoot(), "groktimizer.toml"), "utf8");
  const match = config.match(/^shared_repo\s*=\s*["']([^"']+)["']/m);
  if (!match) throw new Error("shared_repo is missing from groktimizer.toml");
  const coordinates = match[1].match(/github\.com(?::|\/)([^/]+)\/([^/]+?)(?:\.git)?$/);
  if (!coordinates) throw new Error("shared_repo must be a GitHub repository");
  return { owner: coordinates[1], repo: coordinates[2] };
}

async function readResultFile(filename: string) {
  const resultsRoot = resolve(controlPlaneRoot(), "results");
  const localPath = resolve(resultsRoot, filename);
  if (existsSync(localPath)) return readFileSync(localPath, "utf8");

  const { owner, repo } = configuredSharedRepo();
  loadControlPlaneEnv();
  const token = process.env.GITHUB_TOKEN ?? process.env.GH_TOKEN;
  const response = await fetch(
    `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/results/${encodeURIComponent(filename)}?ref=main`,
    {
      cache: "no-store",
      headers: {
        Accept: "application/vnd.github.raw+json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "X-GitHub-Api-Version": "2022-11-28",
      },
    },
  );
  if (!response.ok) throw new Error(`Unable to read ${filename} from the configured research repo`);
  return response.text();
}

export async function loadCommittedBaseline(): Promise<BaselineSnapshot> {
  if (baselineCache && baselineCache.expiresAt > Date.now()) return baselineCache.value;
  const [benchmarkText, throughputText, accuracyText] = await Promise.all([
    readResultFile("bench_results.json"),
    readResultFile("tput_results.json"),
    readResultFile("mc_results.json"),
  ]);
  const benchmark = JSON.parse(benchmarkText) as Record<string, RawBenchResult>;
  const throughput = JSON.parse(throughputText) as RawThroughputResult[];
  const accuracy = JSON.parse(accuracyText) as RawAccuracyResult[];

  const value = {
    hardware: {
      gpu: "NVIDIA RTX PRO 6000 Blackwell",
      vramGb: 96,
      contextTokens: 32_768,
    },
    latency: Object.entries(benchmark)
      .map(([promptTokens, result]) => ({
        promptTokens: Number(promptTokens),
        ttftMs: result.ttft_ms,
        decodeTps: result.decode_tps,
        prefillTps: result.prefill_tps,
      }))
      .sort((left, right) => left.promptTokens - right.promptTokens),
    throughput: throughput.map((result) => ({
      concurrency: result.concurrency,
      aggregateDecodeTps: result.agg_decode_tps,
      perStreamTps: result.per_stream_tps,
      medianTtftMs: result.median_ttft_ms,
      endToEndTps: result.e2e_tps,
    })),
    accuracy: accuracy.map((result) => ({
      task: result.task,
      correct: result.correct,
      total: result.total,
      accuracy: result.acc,
      unparsed: result.unparsed,
    })),
  } satisfies BaselineSnapshot;
  baselineCache = { expiresAt: Date.now() + 60_000, value };
  return value;
}
