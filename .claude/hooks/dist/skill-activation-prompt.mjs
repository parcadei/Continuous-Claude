#!/usr/bin/env node

// src/skill-activation-prompt.ts
import { readFileSync, existsSync } from "fs";
import { join } from "path";
async function main() {
  try {
    const input = readFileSync(0, "utf-8");
    const data = JSON.parse(input);
    const prompt = data.prompt.toLowerCase();
    const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
    const homeDir = process.env.HOME || "";
    const projectRulesPath = join(projectDir, ".claude", "skills", "skill-rules.json");
    const globalRulesPath = join(homeDir, ".claude", "skills", "skill-rules.json");
    let rulesPath = "";
    if (existsSync(projectRulesPath)) {
      rulesPath = projectRulesPath;
    } else if (existsSync(globalRulesPath)) {
      rulesPath = globalRulesPath;
    } else {
      process.exit(0);
    }
    const rules = JSON.parse(readFileSync(rulesPath, "utf-8"));
    const matchedSkills = [];
    for (const [skillName, config] of Object.entries(rules.skills)) {
      const triggers = config.promptTriggers;
      if (!triggers) {
        continue;
      }
      if (triggers.keywords) {
        const keywordMatch = triggers.keywords.some(
          (kw) => prompt.includes(kw.toLowerCase())
        );
        if (keywordMatch) {
          matchedSkills.push({ name: skillName, matchType: "keyword", config });
          continue;
        }
      }
      if (triggers.intentPatterns) {
        const intentMatch = triggers.intentPatterns.some((pattern) => {
          const regex = new RegExp(pattern, "i");
          return regex.test(prompt);
        });
        if (intentMatch) {
          matchedSkills.push({ name: skillName, matchType: "intent", config });
        }
      }
    }
    const matchedAgents = [];
    if (rules.agents) {
      for (const [agentName, config] of Object.entries(rules.agents)) {
        const triggers = config.promptTriggers;
        if (!triggers) {
          continue;
        }
        if (triggers.keywords) {
          const keywordMatch = triggers.keywords.some(
            (kw) => prompt.includes(kw.toLowerCase())
          );
          if (keywordMatch) {
            matchedAgents.push({ name: agentName, matchType: "keyword", config, isAgent: true });
            continue;
          }
        }
        if (triggers.intentPatterns) {
          const intentMatch = triggers.intentPatterns.some((pattern) => {
            const regex = new RegExp(pattern, "i");
            return regex.test(prompt);
          });
          if (intentMatch) {
            matchedAgents.push({ name: agentName, matchType: "intent", config, isAgent: true });
          }
        }
      }
    }
    if (matchedSkills.length > 0 || matchedAgents.length > 0) {
      let output = "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n";
      output += "\u{1F3AF} SKILL ACTIVATION CHECK\n";
      output += "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n";
      const critical = matchedSkills.filter((s) => s.config.priority === "critical");
      const high = matchedSkills.filter((s) => s.config.priority === "high");
      const medium = matchedSkills.filter((s) => s.config.priority === "medium");
      const low = matchedSkills.filter((s) => s.config.priority === "low");
      if (critical.length > 0) {
        output += "\u26A0\uFE0F CRITICAL SKILLS (REQUIRED):\n";
        critical.forEach((s) => output += `  \u2192 ${s.name}
`);
        output += "\n";
      }
      if (high.length > 0) {
        output += "\u{1F4DA} RECOMMENDED SKILLS:\n";
        high.forEach((s) => output += `  \u2192 ${s.name}
`);
        output += "\n";
      }
      if (medium.length > 0) {
        output += "\u{1F4A1} SUGGESTED SKILLS:\n";
        medium.forEach((s) => output += `  \u2192 ${s.name}
`);
        output += "\n";
      }
      if (low.length > 0) {
        output += "\u{1F4CC} OPTIONAL SKILLS:\n";
        low.forEach((s) => output += `  \u2192 ${s.name}
`);
        output += "\n";
      }
      if (matchedAgents.length > 0) {
        output += "\u{1F916} RECOMMENDED AGENTS (token-efficient):\n";
        matchedAgents.forEach((a) => output += `  \u2192 ${a.name}
`);
        output += "\n";
      }
      if (matchedSkills.length > 0) {
        output += "ACTION: Use Skill tool BEFORE responding\n";
      }
      if (matchedAgents.length > 0) {
        output += "ACTION: Use Task tool with agent for exploration\n";
      }
      output += "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n";
      console.log(output);
    }
    const sessionId = process.env.CLAUDE_SESSION_ID || process.env.CLAUDE_PPID || "default";
    const contextFile = `/tmp/claude-context-pct-${sessionId}.txt`;
    if (existsSync(contextFile)) {
      try {
        const pct = parseInt(readFileSync(contextFile, "utf-8").trim(), 10);
        let contextWarning = "";
        if (pct >= 90) {
          contextWarning = "\n" + "=".repeat(50) + "\n  CONTEXT CRITICAL: " + pct + "%\n  Run /create_handoff NOW before auto-compact!\n" + "=".repeat(50) + "\n";
        } else if (pct >= 80) {
          contextWarning = "\nCONTEXT WARNING: " + pct + "%\nRecommend: /create_handoff then /clear soon\n";
        } else if (pct >= 70) {
          contextWarning = "\nContext at " + pct + "%. Consider handoff when you reach a stopping point.\n";
        }
        if (contextWarning) {
          console.log(contextWarning);
        }
      } catch {
      }
    }
    process.exit(0);
  } catch (err) {
    console.error("Error in skill-activation-prompt hook:", err);
    process.exit(1);
  }
}
main().catch((err) => {
  console.error("Uncaught error:", err);
  process.exit(1);
});
