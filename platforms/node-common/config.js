"use strict";

const fs = require("node:fs");
const path = require("node:path");

function removeTomlComment(value) {
  let quote = null;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if ((character === '"' || character === "'") && value[index - 1] !== "\\") {
      quote = quote === character ? null : quote || character;
    }
    if (character === "#" && quote === null) return value.slice(0, index).trim();
  }
  return value.trim();
}

function splitTomlArray(value) {
  const items = [];
  let quote = null;
  let start = 0;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if ((character === '"' || character === "'") && value[index - 1] !== "\\") {
      quote = quote === character ? null : quote || character;
    } else if (character === "," && quote === null) {
      items.push(value.slice(start, index).trim());
      start = index + 1;
    }
  }
  if (value.slice(start).trim()) items.push(value.slice(start).trim());
  return items;
}

function parseTomlValue(raw) {
  const value = removeTomlComment(raw);
  if (value.startsWith("[") && value.endsWith("]")) {
    return splitTomlArray(value.slice(1, -1)).map(parseTomlValue);
  }
  if (value === "true") return true;
  if (value === "false") return false;
  if (/^-?\d+$/.test(value)) return Number(value);
  if (/^-?(?:\d+\.\d+|\d+\.\d*e[+-]?\d+)$/i.test(value)) return Number(value);
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    if (value.startsWith('"')) {
      try {
        return JSON.parse(value);
      } catch {
        throw new Error(`Invalid TOML string: ${value}`);
      }
    }
    return value.slice(1, -1);
  }
  throw new Error(`Unsupported TOML value: ${value}`);
}

function assignTomlValue(target, section, key, value) {
  const parts = [...section, key];
  let cursor = target;
  for (const part of parts.slice(0, -1)) {
    cursor[part] ||= {};
    cursor = cursor[part];
  }
  cursor[parts.at(-1)] = parseTomlValue(value);
}

function parseToml(text) {
  const result = {};
  let section = [];
  for (const [lineNumber, rawLine] of text.split(/\r?\n/).entries()) {
    const line = removeTomlComment(rawLine).trim();
    if (!line) continue;
    const sectionMatch = line.match(/^\[([^\]]+)\]$/);
    if (sectionMatch) {
      section = sectionMatch[1]
        .split(".")
        .map((part) => part.trim())
        .filter(Boolean);
      if (section.length === 0) throw new Error(`Invalid TOML section at line ${lineNumber + 1}`);
      continue;
    }
    const separator = line.indexOf("=");
    if (separator < 1) throw new Error(`Invalid TOML assignment at line ${lineNumber + 1}`);
    assignTomlValue(
      result,
      section,
      line.slice(0, separator).trim(),
      line.slice(separator + 1).trim(),
    );
  }
  return result;
}

function loadTomlConfig(projectRoot, env = process.env) {
  const configuredPath = env.POLYVERSE_CONFIG_FILE || path.join(projectRoot, "config.toml");
  const configPath = path.resolve(projectRoot, configuredPath);
  if (!fs.existsSync(configPath)) return {};
  return parseToml(fs.readFileSync(configPath, "utf8"));
}

function tomlGate(projectConfig, name) {
  return projectConfig?.platforms?.[name] || {};
}

function tomlRuntime(projectConfig) {
  return projectConfig?.runtime || {};
}

function valueOr(env, key, tomlValue, fallback) {
  return env[key] !== undefined ? env[key] : tomlValue !== undefined ? tomlValue : fallback;
}

function parseIds(value) {
  if (Array.isArray(value)) return new Set(value.map((item) => String(item).trim()).filter(Boolean));
  return parseCsv(value);
}

function parseCsv(value) {
  return new Set(
    String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

function parseBoolean(value, fallback = false) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  if (value === true || value === false) return value;
  if (value === "true") return true;
  if (value === "false") return false;
  throw new Error(`Expected true or false, received: ${value}`);
}

function parseInteger(value, fallback, minimum, maximum, name) {
  const parsed = value === undefined || value === "" ? fallback : Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}

module.exports = {
  loadTomlConfig,
  parseBoolean,
  parseCsv,
  parseIds,
  parseInteger,
  tomlGate,
  tomlRuntime,
  valueOr,
};
